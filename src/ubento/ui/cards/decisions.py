"""Card "Decisões": linha do tempo das decisões tomadas (rolável, com esmaecimento no rodapé).

Propostas de agentes no modo "pedir aprovação" aparecem com os botões ✓ e ✕.
"""

from __future__ import annotations

from datetime import datetime
from typing import Callable

from PySide6.QtCore import QPointF, QRectF, Qt, Signal
from PySide6.QtGui import QColor, QFontMetrics, QLinearGradient, QPainter, QPen
from PySide6.QtWidgets import QVBoxLayout, QWidget

from ...formatting import MASK, ago, is_hidden
from ...store import Decision, Store
from .. import icons, theme
from ..components import Card, Label, setup

W = theme.W
ROW_H = 68
ICONS = {"buy": "trending-up", "sell": "trending-down", "hold": "pause", "rebalance": "repeat", "swap": "swap"}
KIND_LABELS = {"buy": "Compra", "sell": "Venda", "hold": "Manutenção", "rebalance": "Rebalanceamento", "swap": "Swap"}
STATUS_TAGS = {"proposed": ("Proposta", theme.WARNING), "suggested": ("Sugestão", theme.BLUE_SOFT), "rejected": ("Recusada", theme.MUTED)}

AgentLookup = Callable[[str], "tuple[str, str] | None"]  # id -> (nome, cor)


class DecisionList(QWidget):
    resolve_requested = Signal(str, bool)  # (uid da decisão, aprovada?)

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

    def _hit_button(self, pos: QPointF) -> tuple[Decision, bool] | None:
        i = int((pos.y() + self._offset) // ROW_H)
        items = self.items()
        if not 0 <= i < len(items) or items[i].status != "proposed":
            return None
        ok, no = self._buttons(i * ROW_H - self._offset)
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
        if hit:
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
        now = datetime.now()
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
        edge = w - (84 if proposed else 0)  # as propostas reservam espaço para ✓ ✕
        p.setOpacity(0.5 if d.status == "rejected" else 1.0)
        if hovered or proposed:
            p.setBrush(QColor(255, 255, 255, 10 if hovered else 6))
            p.setPen(Qt.PenStyle.NoPen)
            p.drawRoundedRect(QRectF(-8, y + 2, w + 16, ROW_H - 4), 14, 14)
        p.setBrush(QColor("#11111A"))
        p.setPen(QPen(QColor("#1B1B27"), 1))
        p.drawEllipse(QRectF(0.5, y + (ROW_H - 52) / 2 + 0.5, 51, 51))
        p.drawPixmap(QPointF(18, y + (ROW_H - 18) / 2), icons.pixmap(ICONS.get(d.kind, "swap"), theme.TEXT, 18, 1.9))

        # efeito (à direita): inteiro em branco, centavos/moeda em cinza
        right_w = 0.0
        if d.amount_text:
            p.setFont(theme.font(16, W.Medium))
            fm = p.fontMetrics()
            sign, _, rest = d.amount_text.partition(" ")
            whole, comma, tail = rest.partition(",")
            main, dim = (f"{sign} {MASK}", "") if is_hidden() else (f"{sign} {whole}", f"{comma}{tail}")
            dim_w = fm.horizontalAdvance(dim)
            p.setPen(QColor(theme.MUTED))
            p.drawText(QRectF(edge - dim_w - 2, y + 11, dim_w + 4, 22), Qt.AlignmentFlag.AlignVCenter, dim)
            main_w = fm.horizontalAdvance(main)
            p.setPen(QColor(theme.TEXT))
            p.drawText(QRectF(edge - dim_w - 2 - main_w - 2, y + 11, main_w + 4, 22), Qt.AlignmentFlag.AlignVCenter, main)
            right_w = dim_w + main_w + 14

        # metadados da linha de baixo (à direita): [● agente ·] tempo
        p.setFont(theme.font(13, W.Normal))
        fm = p.fontMetrics()
        label = ago(d.moment, now)
        label_w = fm.horizontalAdvance(label)
        agent = self.lookup(d.agent) if (self.lookup and d.agent) else None
        agent_name = fm.elidedText(agent[0], Qt.TextElideMode.ElideRight, 90) if agent else ""
        meta_w = label_w + ((fm.horizontalAdvance(agent_name) + 26) if agent else 0)

        # título ocupa a largura toda que o efeito deixa livre
        p.setPen(QColor(theme.TEXT))
        p.setFont(theme.font(16, W.Medium))
        title_room = max(60.0, edge - 68 - max(right_w, 90))
        title = QFontMetrics(p.font()).elidedText(d.title, Qt.TextElideMode.ElideRight, int(title_room))
        p.drawText(QRectF(68, y + 11, title_room, 22), Qt.AlignmentFlag.AlignVCenter, title)

        # justificativa, precedida pela etiqueta de status (Proposta / Sugestão / Recusada)
        x = 68.0
        tag = STATUS_TAGS.get(d.status)
        if tag:
            p.setFont(theme.font(11, W.DemiBold))
            tag_w = p.fontMetrics().horizontalAdvance(tag[0]) + 16
            color = QColor(tag[1])
            p.setBrush(QColor(color.red(), color.green(), color.blue(), 30))
            p.setPen(Qt.PenStyle.NoPen)
            p.drawRoundedRect(QRectF(x, y + 36, tag_w, 18), 9, 9)
            p.setPen(color)
            p.drawText(QRectF(x, y + 36, tag_w, 18), Qt.AlignmentFlag.AlignCenter, tag[0])
            x += tag_w + 8
        p.setPen(QColor(theme.DIM))
        p.setFont(theme.font(13, W.Normal))
        room = max(20.0, edge - x - meta_w - 14)
        detail = QFontMetrics(p.font()).elidedText(d.detail, Qt.TextElideMode.ElideRight, int(room))
        p.drawText(QRectF(x, y + 35, room, 20), Qt.AlignmentFlag.AlignVCenter, detail)

        p.setPen(QColor(theme.DIM))
        p.drawText(QRectF(edge - label_w - 4, y + 35, label_w + 4, 20), Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter, label)
        if agent:
            nw = fm.horizontalAdvance(agent_name)
            gap = label_w + 14
            p.setPen(QColor(theme.MUTED))
            p.drawText(QRectF(edge - gap - nw - 4, y + 35, nw + 6, 20), Qt.AlignmentFlag.AlignVCenter, agent_name)
            p.setBrush(QColor(agent[1]))
            p.setPen(Qt.PenStyle.NoPen)
            p.drawEllipse(QPointF(edge - gap - nw - 12, y + 45), 4, 4)

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

    def __init__(self, store: Store, lookup: AgentLookup | None = None, parent=None):
        super().__init__(parent)
        self.list = DecisionList(store, lookup)
        self.list.resolve_requested.connect(self.resolve_requested)
        v = QVBoxLayout(self)
        v.setContentsMargins(22, 20, 22, 0)
        v.setSpacing(0)
        v.addWidget(Label("Decisões", 26, W.DemiBold))
        v.addSpacing(10)
        v.addWidget(self.list, 1)
        store.changed.connect(self.list.reset_scroll)

    def refresh(self) -> None:
        self.list.update()
