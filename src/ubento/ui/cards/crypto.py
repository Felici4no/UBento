"""Card "Saldo em cripto": total + barra de alocação por ativo."""

from __future__ import annotations

from PySide6.QtCore import QRectF, Qt
from PySide6.QtGui import QColor, QPainter, QPen
from PySide6.QtWidgets import QHBoxLayout, QToolTip, QVBoxLayout, QWidget

from ...formatting import compact, pct
from .. import theme
from ..components import Card, DeltaLabel, Label, MoneyText, setup

W = theme.W
BLEND = 0.35  # peso da participação real na largura; o resto é distribuído por igual (rótulos legíveis)


class AllocationBar(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self._items: list[tuple[str, float]] = []
        self._hover = -1
        self.setMouseTracking(True)
        self.setMinimumHeight(64)

    def set_items(self, items: list[tuple[str, float]]) -> None:
        self._items = items
        self.update()

    def _segments(self) -> list[QRectF]:
        n = len(self._items)
        total = sum(v for _, v in self._items) or 1
        gap = 7.0
        usable = self.width() - gap * (n - 1)
        weights = [BLEND * v / total + (1 - BLEND) / n for _, v in self._items]
        x, rects = 0.0, []
        for w in weights:
            rects.append(QRectF(x, 0, usable * w, 5))
            x += usable * w + gap
        return rects

    def _index_at(self, x: float) -> int:
        for i, r in enumerate(self._segments()):
            if r.left() - 3 <= x <= r.right() + 3:
                return i
        return -1

    def mouseMoveEvent(self, e) -> None:
        i = self._index_at(e.position().x())
        if i != self._hover:
            self._hover = i
            self.update()
        if i >= 0:
            sym, val = self._items[i]
            share = val / (sum(v for _, v in self._items) or 1) * 100
            QToolTip.showText(e.globalPosition().toPoint(), f"{sym} · {pct(share)} da carteira", self)
        else:
            QToolTip.hideText()

    def leaveEvent(self, _e) -> None:
        self._hover = -1
        QToolTip.hideText()
        self.update()

    def paintEvent(self, _e) -> None:
        if not self._items:
            return
        p = QPainter(self)
        setup(p)
        segs = self._segments()
        n = len(segs)
        sym_font, val_font = theme.font(11, W.Bold), theme.font(15, W.Medium)
        for i, ((sym, value), seg) in enumerate(zip(self._items, segs)):
            color = QColor(theme.ASSET_COLORS[sym])
            dimmed = self._hover >= 0 and i != self._hover
            if dimmed:
                color.setAlpha(90)
            p.setPen(QPen(color, 5 if i != self._hover else 6, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
            p.drawLine(int(seg.left() + 2.5), 3, int(seg.right() - 2.5), 3)

            left_aligned = i < n - 2
            align = Qt.AlignmentFlag.AlignLeft if left_aligned else Qt.AlignmentFlag.AlignRight
            x0, w = (seg.left(), 90) if left_aligned else (seg.right() - 90, 90)
            p.setFont(sym_font)
            p.setPen(color if not dimmed else QColor(color.red(), color.green(), color.blue(), 120))
            p.drawText(QRectF(x0, 20, w, 14), align | Qt.AlignmentFlag.AlignVCenter, sym)
            p.setFont(val_font)
            p.setPen(QColor(theme.TEXT if not dimmed else theme.MUTED))
            p.drawText(QRectF(x0, 38, w, 20), align | Qt.AlignmentFlag.AlignVCenter, compact(value))


class CryptoCard(Card):
    def __init__(self, store, parent=None):
        super().__init__(parent)
        self.store = store
        self.total = MoneyText(30)
        self.delta = DeltaLabel(13)
        self.bar = AllocationBar()

        row = QHBoxLayout()
        row.setSpacing(8)
        row.addWidget(self.total)
        row.addWidget(self.delta, 0, Qt.AlignmentFlag.AlignBottom)
        row.addStretch()

        v = QVBoxLayout(self)
        v.setContentsMargins(22, 20, 22, 18)
        v.setSpacing(2)
        v.addWidget(Label("Saldo em cripto", 14, W.Normal, theme.MUTED))
        v.addLayout(row)
        v.addSpacing(14)
        v.addWidget(self.bar)
        v.addStretch(1)
        store.changed.connect(self.refresh)
        self.refresh()

    def refresh(self) -> None:
        self.total.set_amount(self.store.crypto_total())
        self.delta.set_value(self.store.crypto_change)
        self.bar.set_items(self.store.crypto_breakdown())

