"""Card "Transferências": lista rolável com esmaecimento no rodapé."""

from __future__ import annotations

from datetime import datetime

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QColor, QLinearGradient, QPainter, QPen
from PySide6.QtWidgets import QVBoxLayout, QWidget

from ...formatting import ago
from ...store import Store, Transfer
from .. import icons, theme
from ..components import Card, Label, setup

W = theme.W
ROW_H = 68
ICONS = {"sent": "arrow-up-right", "received": "arrow-down-left", "swap": "swap"}


class TransferList(QWidget):
    def __init__(self, store: Store, parent=None):
        super().__init__(parent)
        self.store = store
        self._offset = 0.0
        self._hover = -1
        self.setMouseTracking(True)

    def _max_offset(self) -> float:
        return max(0.0, len(self.store.transfers) * ROW_H - self.height() + 8)

    def wheelEvent(self, e) -> None:
        self._offset = min(self._max_offset(), max(0.0, self._offset - e.angleDelta().y() / 2))
        self.update()

    def mouseMoveEvent(self, e) -> None:
        i = int((e.position().y() + self._offset) // ROW_H)
        self._hover = i if 0 <= i < len(self.store.transfers) else -1
        self.update()

    def leaveEvent(self, _e) -> None:
        self._hover = -1
        self.update()

    def paintEvent(self, _e) -> None:
        p = QPainter(self)
        setup(p)
        now = datetime.now()
        for i, t in enumerate(self.store.transfers):
            y = i * ROW_H - self._offset
            if y + ROW_H < 0 or y > self.height():
                continue
            self._paint_row(p, t, y, now, hovered=i == self._hover)

        fade = QLinearGradient(0, self.height() - 74, 0, self.height())
        fade.setColorAt(0, QColor(6, 6, 8, 0))
        fade.setColorAt(1, QColor(theme.CARD))
        p.fillRect(QRectF(0, self.height() - 74, self.width(), 74), fade)
        if self._offset > 0:
            top = QLinearGradient(0, 0, 0, 24)
            top.setColorAt(0, QColor(theme.CARD))
            top.setColorAt(1, QColor(6, 6, 8, 0))
            p.fillRect(QRectF(0, 0, self.width(), 24), top)

    def _paint_row(self, p: QPainter, t: Transfer, y: float, now: datetime, hovered: bool) -> None:
        w = self.width()
        if hovered:
            p.setBrush(QColor(255, 255, 255, 10))
            p.setPen(Qt.PenStyle.NoPen)
            p.drawRoundedRect(QRectF(-8, y + 2, w + 16, ROW_H - 4), 14, 14)
        p.setBrush(QColor("#11111A"))
        p.setPen(QPen(QColor("#1B1B27"), 1))
        p.drawEllipse(QRectF(0.5, y + (ROW_H - 52) / 2 + 0.5, 51, 51))
        p.drawPixmap(QPointF(18, y + (ROW_H - 18) / 2), icons.pixmap(ICONS.get(t.kind, "swap"), theme.TEXT, 18, 1.9))

        p.setPen(QColor(theme.TEXT))
        p.setFont(theme.font(16, W.Medium))
        p.drawText(QRectF(68, y + 11, w - 190, 22), Qt.AlignmentFlag.AlignVCenter, t.title)
        p.setPen(QColor(theme.DIM))
        p.setFont(theme.font(13, W.Normal))
        p.drawText(QRectF(68, y + 35, w - 190, 20), Qt.AlignmentFlag.AlignVCenter, t.subtitle)

        sign, _, rest = t.amount_text.partition(" ")
        whole, comma, dec = rest.partition(",")
        main = f"{sign} {whole}"
        p.setFont(theme.font(16, W.Medium))
        right = w
        # moeda + centavos em cinza, parte inteira em branco
        unit = ""
        if " " in dec:
            dec, _, unit = dec.partition(" ")
        tail = f"{comma}{dec} {unit}".rstrip()
        fm = p.fontMetrics()
        tail_w = fm.horizontalAdvance(tail)
        p.setPen(QColor(theme.MUTED))
        p.drawText(QRectF(right - tail_w - 2, y + 11, tail_w + 4, 22), Qt.AlignmentFlag.AlignVCenter, tail)
        p.setPen(QColor(theme.TEXT))
        p.drawText(QRectF(right - tail_w - 2 - fm.horizontalAdvance(main) - 2, y + 11, fm.horizontalAdvance(main) + 4, 22), Qt.AlignmentFlag.AlignVCenter, main)
        p.setPen(QColor(theme.DIM))
        p.setFont(theme.font(13, W.Normal))
        p.drawText(QRectF(w - 160, y + 35, 160, 20), Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter, ago(t.moment, now))


class TransfersCard(Card):
    def __init__(self, store: Store, parent=None):
        super().__init__(parent)
        self.list = TransferList(store)
        v = QVBoxLayout(self)
        v.setContentsMargins(22, 20, 22, 0)
        v.setSpacing(0)
        v.addWidget(Label("Transferências", 26, W.DemiBold))
        v.addSpacing(10)
        v.addWidget(self.list, 1)
        store.changed.connect(self._on_change)

    def _on_change(self) -> None:
        self.list._offset = 0.0
        self.list.update()

