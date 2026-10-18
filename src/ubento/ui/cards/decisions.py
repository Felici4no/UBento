"""Card "Decisões": linha do tempo das decisões tomadas (rolável, com esmaecimento no rodapé)."""

from __future__ import annotations

from datetime import datetime
from typing import Callable

from PySide6.QtCore import QPointF, QRectF, Qt
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

AgentLookup = Callable[[str], "tuple[str, str] | None"]  # id -> (nome, cor)


class DecisionList(QWidget):
    def __init__(self, store: Store, lookup: AgentLookup | None = None, parent=None):
        super().__init__(parent)
        self.store = store
        self.lookup = lookup  # só na aba Geral: mostra de qual agente veio cada decisão
        self._offset = 0.0
        self._hover = -1
        self.setMouseTracking(True)

    def _max_offset(self) -> float:
        return max(0.0, len(self.store.decisions) * ROW_H - self.height() + 8)

    def reset_scroll(self) -> None:
        self._offset = 0.0
        self.update()

    def wheelEvent(self, e) -> None:
        self._offset = min(self._max_offset(), max(0.0, self._offset - e.angleDelta().y() / 2))
        self.update()

    def mouseMoveEvent(self, e) -> None:
        i = int((e.position().y() + self._offset) // ROW_H)
        self._hover = i if 0 <= i < len(self.store.decisions) else -1
        self.update()

    def leaveEvent(self, _e) -> None:
        self._hover = -1
        self.update()

    def paintEvent(self, _e) -> None:
        p = QPainter(self)
        setup(p)
        now = datetime.now()
        for i, d in enumerate(self.store.decisions):
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
        if hovered:
            p.setBrush(QColor(255, 255, 255, 10))
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
            p.drawText(QRectF(w - dim_w - 2, y + 11, dim_w + 4, 22), Qt.AlignmentFlag.AlignVCenter, dim)
            main_w = fm.horizontalAdvance(main)
            p.setPen(QColor(theme.TEXT))
            p.drawText(QRectF(w - dim_w - 2 - main_w - 2, y + 11, main_w + 4, 22), Qt.AlignmentFlag.AlignVCenter, main)
            right_w = dim_w + main_w + 14

        text_w = w - 68 - max(right_w, 90)
        p.setPen(QColor(theme.TEXT))
        p.setFont(theme.font(16, W.Medium))
        p.drawText(QRectF(68, y + 11, text_w, 22), Qt.AlignmentFlag.AlignVCenter, d.title)
        p.setPen(QColor(theme.DIM))
        p.setFont(theme.font(13, W.Normal))
        detail = QFontMetrics(p.font()).elidedText(d.detail, Qt.TextElideMode.ElideRight, int(w - 68 - 120))
        p.drawText(QRectF(68, y + 35, w - 68 - 120, 20), Qt.AlignmentFlag.AlignVCenter, detail)

        # linha inferior à direita: [● agente ·] tempo
        label = ago(d.moment, now)
        p.setFont(theme.font(13, W.Normal))
        fm = p.fontMetrics()
        x_right = w
        p.setPen(QColor(theme.DIM))
        p.drawText(QRectF(x_right - 120, y + 35, 120, 20), Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter, label)
        agent = self.lookup(d.agent) if (self.lookup and d.agent) else None
        if agent:
            name, color = agent
            gap = fm.horizontalAdvance(label) + 14
            name = fm.elidedText(name, Qt.TextElideMode.ElideRight, 90)
            nw = fm.horizontalAdvance(name)
            p.setPen(QColor(theme.MUTED))
            p.drawText(QRectF(x_right - gap - nw - 4, y + 35, nw + 6, 20), Qt.AlignmentFlag.AlignVCenter, name)
            p.setBrush(QColor(color))
            p.setPen(Qt.PenStyle.NoPen)
            p.drawEllipse(QPointF(x_right - gap - nw - 12, y + 45), 4, 4)


class DecisionsCard(Card):
    def __init__(self, store: Store, lookup: AgentLookup | None = None, parent=None):
        super().__init__(parent)
        self.list = DecisionList(store, lookup)
        v = QVBoxLayout(self)
        v.setContentsMargins(22, 20, 22, 0)
        v.setSpacing(0)
        v.addWidget(Label("Decisões", 26, W.DemiBold))
        v.addSpacing(10)
        v.addWidget(self.list, 1)
        store.changed.connect(self.list.reset_scroll)

    def refresh(self) -> None:
        self.list.update()
