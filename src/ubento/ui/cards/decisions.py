"""Card "Decisões": o registro (log) das decisões tomadas, rolável, com esmaecimento no rodapé.

Cada linha é uma entrada de log: título e justificativa, o RESULTADO (verde no lucro, vermelho na perda, já líquido da taxa), e uma linha de
registro com data e hora, o movimento, o valor aplicado e a taxa. Propostas de agentes no modo "pedir aprovação" aparecem com os botões ✓ e ✕
(sem resultado: ele só existe depois de executada).
"""

from __future__ import annotations

from datetime import datetime
from typing import Callable

from PySide6.QtCore import QPointF, QRectF, Qt, Signal
from PySide6.QtGui import QColor, QFontMetrics, QLinearGradient, QPainter, QPen
from PySide6.QtWidgets import QVBoxLayout, QWidget

from ...formatting import MASK, is_hidden, number
from ...store import Decision, Store
from .. import icons, theme
from ..components import Card, Label, setup

W = theme.W
ROW_H = 84
ICONS = {"buy": "trending-up", "sell": "trending-down", "hold": "pause", "rebalance": "repeat", "swap": "swap"}
KIND_LABELS = {"buy": "Compra", "sell": "Venda", "hold": "Manutenção", "rebalance": "Rebalanceamento", "swap": "Swap"}
STATUS_TAGS = {"proposed": ("Proposta", theme.WARNING), "approved": ("Aprovada", theme.GREEN),
               "suggested": ("Sugestão", theme.BLUE_SOFT), "rejected": ("Recusada", theme.MUTED)}

AgentLookup = Callable[[str], "tuple[str, str] | None"]  # id -> (nome, cor)


def resultado_cor(valor: float | None) -> str:
    """Verde no lucro, vermelho na perda, cinza quando não há resultado (ou é zero)."""
    if valor is None or round(valor, 2) == 0:
        return theme.MUTED
    return theme.GREEN if valor > 0 else theme.RED


def usd_texto(valor: float, sinal: bool = False) -> str:
    """`1234.5` -> `US$ 1.234,50`; com `sinal`, `+US$ …` / `−US$ …`. Respeita o modo "ocultar valores"."""
    if is_hidden():
        return f"US$ {MASK}"
    prefixo = ("+" if valor > 0 else "−" if valor < 0 else "") if sinal else ""
    return f"{prefixo}US$ {number(abs(valor), 2)}"


def resultado_info(d: Decision) -> tuple[str, str, str] | None:
    """(texto, cor, rótulo) do resultado de uma decisão EXECUTADA com movimento; None nos demais casos."""
    if d.status != "executed" or d.pnl_usd is None:
        return None
    rotulo = "realizado, líquido da taxa" if d.pnl_realizado else "em aberto, líquido da taxa"
    return usd_texto(d.pnl_usd, sinal=True), resultado_cor(d.pnl_usd), rotulo


def linha_de_log(d: Decision) -> str:
    """A linha de registro: data e hora (com segundos), o movimento, o valor aplicado e a taxa."""
    partes = [d.moment.strftime("%d/%m/%Y %H:%M:%S")]
    if d.amount_text:
        partes.append(f"{d.amount_text.split(' ', 1)[0]} {MASK}" if is_hidden() and " " in d.amount_text else d.amount_text)
    if d.value_usd is not None:
        partes.append(f"Valor {usd_texto(d.value_usd)}")
        partes.append(f"Taxa {usd_texto(d.fee_usd)}")
    return "  ·  ".join(partes)


class DecisionList(QWidget):
    resolve_requested = Signal(str, bool)  # (uid da decisão, aprovada?)
    registrar_requested = Signal(str)  # uid de uma decisão aprovada cuja execução será registrada

    def __init__(self, store: Store, lookup: AgentLookup | None = None, parent=None):
        super().__init__(parent)
        self.store = store
        self.lookup = lookup  # só na aba Geral: mostra de qual agente veio cada decisão
        self._offset = 0.0
        self._hover = -1
        self.kind: str | None = None  # filtro por tipo de decisão
        self.setMouseTracking(True)

    def items(self) -> list[Decision]:
        return [d for d in self.store.decisions if self.kind in (None, d.kind)]

    def set_filter(self, kind: str | None) -> None:
        self.kind = kind
        self.reset_scroll()

    def _max_offset(self) -> float:
        return max(0.0, len(self.items()) * ROW_H - self.height() + 8)

    def reset_scroll(self) -> None:
        self._offset = 0.0
        self.update()

    # -- interação ---------------------------------------------------------

    def _buttons(self, row_y: float) -> tuple[QRectF, QRectF]:
        w = self.width()
        return QRectF(w - 72, row_y + (ROW_H - 30) / 2, 30, 30), QRectF(w - 34, row_y + (ROW_H - 30) / 2, 30, 30)

    def _registrar_rect(self, row_y: float) -> QRectF:
        return QRectF(self.width() - 98, row_y + (ROW_H - 30) / 2, 96, 30)

    def _hit_button(self, pos: QPointF) -> tuple[Decision, bool | None] | None:
        """(decisão, True=aprovar / False=recusar / None=registrar execução) se o clique caiu num botão."""
        i = int((pos.y() + self._offset) // ROW_H)
        items = self.items()
        if not 0 <= i < len(items):
            return None
        row_y = i * ROW_H - self._offset
        if items[i].status == "approved":
            return (items[i], None) if self._registrar_rect(row_y).contains(pos) else None
        if items[i].status != "proposed":
            return None
        ok, no = self._buttons(row_y)
        if ok.contains(pos):
            return items[i], True
        if no.contains(pos):
            return items[i], False
        return None

    def wheelEvent(self, e) -> None:
        self._offset = min(self._max_offset(), max(0.0, self._offset - e.angleDelta().y() / 2))
        self.update()

    def mouseMoveEvent(self, e) -> None:
        i = int((e.position().y() + self._offset) // ROW_H)
        self._hover = i if 0 <= i < len(self.items()) else -1
        self.setCursor(Qt.CursorShape.PointingHandCursor if self._hit_button(e.position()) else Qt.CursorShape.ArrowCursor)
        self.update()

    def mousePressEvent(self, e) -> None:
        hit = self._hit_button(e.position()) if e.button() == Qt.MouseButton.LeftButton else None
        if hit and hit[1] is None:
            self.registrar_requested.emit(hit[0].uid)
            e.accept()
        elif hit:
            self.resolve_requested.emit(hit[0].uid, hit[1])
            e.accept()
        else:
            e.ignore()  # deixa o clique subir (expande o card)

    def leaveEvent(self, _e) -> None:
        self._hover = -1
        self.update()

    # -- desenho -----------------------------------------------------------

    def paintEvent(self, _e) -> None:
        p = QPainter(self)
        setup(p)
        now = self.store.mercado.agora()
        for i, d in enumerate(self.items()):
            y = i * ROW_H - self._offset
            if y + ROW_H < 0 or y > self.height():
                continue
            self._paint_row(p, d, y, now, hovered=i == self._hover)

        fade = QLinearGradient(0, self.height() - 74, 0, self.height())
        fade.setColorAt(0, QColor(6, 6, 8, 0))
        fade.setColorAt(1, QColor(theme.CARD))
        p.fillRect(QRectF(0, self.height() - 74, self.width(), 74), fade)
        if self._offset > 0:
            top = QLinearGradient(0, 0, 0, 24)
            top.setColorAt(0, QColor(theme.CARD))
            top.setColorAt(1, QColor(6, 6, 8, 0))
            p.fillRect(QRectF(0, 0, self.width(), 24), top)

    def _paint_row(self, p: QPainter, d: Decision, y: float, now: datetime, hovered: bool) -> None:
        w = self.width()
        proposed = d.status == "proposed"
        approved = d.status == "approved"
        edge = w - (84 if proposed else 112 if approved else 0)  # reserva espaço para ✓ ✕ ou para "Registrar"
        info = resultado_info(d)
        cor = QColor(info[1]) if info else QColor(theme.TEXT)
        p.setOpacity(0.5 if d.status == "rejected" else 1.0)
        if hovered or proposed:
            p.setBrush(QColor(255, 255, 255, 10 if hovered else 6))
            p.setPen(Qt.PenStyle.NoPen)
            p.drawRoundedRect(QRectF(-8, y + 2, w + 16, ROW_H - 4), 14, 14)
        # ícone: o contorno e o traço seguem o resultado (verde, vermelho ou neutro)
        centro_y = y + 36
        p.setBrush(QColor("#11111A"))
        p.setPen(QPen(cor if info else QColor("#1B1B27"), 1.6 if info else 1))
        p.drawEllipse(QRectF(0.5, centro_y - 25.5, 51, 51))
        p.drawPixmap(QPointF(18, centro_y - 9), icons.pixmap(ICONS.get(d.kind, "swap"), cor.name() if info else theme.TEXT, 18, 1.9))

        # coluna da direita: o RESULTADO em destaque e, embaixo, o que ele significa
        right_w = 0.0
        if info:
            texto, _, rotulo = info
            p.setFont(theme.font(17, W.DemiBold))
            right_w = max(p.fontMetrics().horizontalAdvance(texto), 0)
            p.setPen(cor)
            p.drawText(QRectF(edge - right_w - 4, y + 7, right_w + 4, 24), Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter, texto)
            p.setFont(theme.font(11, W.Normal))
            p.setPen(QColor(theme.DIM))
            rot_w = p.fontMetrics().horizontalAdvance(rotulo)
            p.drawText(QRectF(edge - rot_w - 4, y + 30, rot_w + 4, 16), Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter, rotulo)
            right_w = max(right_w, rot_w)

        # título
        p.setPen(QColor(theme.TEXT))
        p.setFont(theme.font(16, W.Medium))
        title_room = max(60.0, edge - 68 - max(right_w, 20) - 12)
        title = QFontMetrics(p.font()).elidedText(d.title, Qt.TextElideMode.ElideRight, int(title_room))
        p.drawText(QRectF(68, y + 8, title_room, 22), Qt.AlignmentFlag.AlignVCenter, title)

        # justificativa, precedida pela etiqueta de status (Proposta / Sugestão / Recusada)
        x = 68.0
        tag = STATUS_TAGS.get(d.status)
        if tag:
            p.setFont(theme.font(11, W.DemiBold))
            tag_w = p.fontMetrics().horizontalAdvance(tag[0]) + 16
            color = QColor(tag[1])
            p.setBrush(QColor(color.red(), color.green(), color.blue(), 30))
            p.setPen(Qt.PenStyle.NoPen)
            p.drawRoundedRect(QRectF(x, y + 32, tag_w, 18), 9, 9)
            p.setPen(color)
            p.drawText(QRectF(x, y + 32, tag_w, 18), Qt.AlignmentFlag.AlignCenter, tag[0])
            x += tag_w + 8
        p.setPen(QColor(theme.MUTED))
        p.setFont(theme.font(13, W.Normal))
        room = max(20.0, edge - x - 8)
        detail = QFontMetrics(p.font()).elidedText(d.detail, Qt.TextElideMode.ElideRight, int(room))
        p.drawText(QRectF(x, y + 31, room, 20), Qt.AlignmentFlag.AlignVCenter, detail)

        # linha de registro (log): data e hora · movimento · valor · taxa, e o agente à direita
        agent = self.lookup(d.agent) if (self.lookup and d.agent) else None
        p.setFont(theme.font(12, W.Normal))
        fm = p.fontMetrics()
        agent_name = fm.elidedText(agent[0], Qt.TextElideMode.ElideRight, 90) if agent else ""
        agent_w = (fm.horizontalAdvance(agent_name) + 22) if agent else 0
        room_log = max(40.0, edge - 68 - agent_w - 8)
        p.setPen(QColor(theme.DIM))
        p.drawText(QRectF(68, y + 55, room_log, 18), Qt.AlignmentFlag.AlignVCenter, fm.elidedText(linha_de_log(d), Qt.TextElideMode.ElideRight, int(room_log)))
        if agent:
            nw = fm.horizontalAdvance(agent_name)
            p.setPen(QColor(theme.MUTED))
            p.drawText(QRectF(edge - nw - 4, y + 55, nw + 6, 18), Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter, agent_name)
            p.setBrush(QColor(agent[1]))
            p.setPen(Qt.PenStyle.NoPen)
            p.drawEllipse(QPointF(edge - nw - 12, y + 64), 4, 4)

        if approved:
            caixa = self._registrar_rect(y)
            p.setBrush(QColor(255, 255, 255, 8))
            p.setPen(QPen(QColor(theme.BLUE_SOFT), 1.3))
            p.drawRoundedRect(caixa.adjusted(0.6, 0.6, -0.6, -0.6), 15, 15)
            p.setPen(QColor(theme.TEXT))
            p.setFont(theme.font(13, W.Medium))
            p.drawText(caixa, Qt.AlignmentFlag.AlignCenter, "Registrar")
        if proposed:
            ok, no = self._buttons(y)
            p.setBrush(QColor("#1F7A45"))
            p.setPen(Qt.PenStyle.NoPen)
            p.drawEllipse(ok)
            p.drawPixmap(QPointF(ok.center().x() - 8, ok.center().y() - 8), icons.pixmap("check", "white", 16, 2.4))
            p.setBrush(QColor(255, 255, 255, 8))
            p.setPen(QPen(QColor(theme.OUTLINE), 1.2))
            p.drawEllipse(no.adjusted(0.6, 0.6, -0.6, -0.6))
            p.drawPixmap(QPointF(no.center().x() - 7, no.center().y() - 7), icons.pixmap("x", theme.TEXT, 14, 2.2))
        p.setOpacity(1.0)


class DecisionsCard(Card):
    resolve_requested = Signal(str, bool)
    registrar_requested = Signal(str)

    def __init__(self, store: Store, lookup: AgentLookup | None = None, parent=None):
        super().__init__(parent)
        self.list = DecisionList(store, lookup)
        self.list.resolve_requested.connect(self.resolve_requested)
        self.list.registrar_requested.connect(self.registrar_requested)
        v = QVBoxLayout(self)
        v.setContentsMargins(22, 20, 22, 0)
        v.setSpacing(0)
        v.addWidget(Label("Decisões", 26, W.DemiBold))
        v.addSpacing(10)
        v.addWidget(self.list, 1)
        store.changed.connect(self.list.reset_scroll)

    def refresh(self) -> None:
        self.list.update()
