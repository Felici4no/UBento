"""Card "Saldo total": período, variação e gráfico de barras interativo."""

from __future__ import annotations

from datetime import date

from PySide6.QtCore import QPointF, QRectF, Qt, QVariantAnimation
from PySide6.QtGui import QColor, QLinearGradient, QPainter, QPen
from PySide6.QtWidgets import QButtonGroup, QHBoxLayout, QVBoxLayout, QWidget

from ...formatting import money, short_date
from ...store import RANGES
from .. import theme
from ..components import Card, DeltaLabel, Label, MoneyText, PillButton, setup

W = theme.W


def _mix(a: QColor, b: QColor, t: float) -> QColor:
    return QColor(
        int(a.red() + (b.red() - a.red()) * t),
        int(a.green() + (b.green() - a.green()) * t),
        int(a.blue() + (b.blue() - a.blue()) * t),
    )


class BarChart(QWidget):
    TOP = 34  # espaço reservado ao tooltip

    def __init__(self, parent=None):
        super().__init__(parent)
        self._points: list[tuple[date, float]] = []
        self._from: list[float] = []
        self._to: list[float] = []
        self._shown: list[float] = []
        self._hover = -1
        self._with_year = False
        self.setMouseTracking(True)
        self._anim = QVariantAnimation(self)
        self._anim.setDuration(320)
        self._anim.setStartValue(0.0)
        self._anim.setEndValue(1.0)
        self._anim.valueChanged.connect(self._tick)

    def set_points(self, points: list[tuple[date, float]], with_year: bool, animate: bool = True) -> None:
        self._points, self._with_year = points, with_year
        values = [v for _, v in points]
        lo, hi = min(values), max(values)
        span = (hi - lo) or 1
        self._from = (self._shown if len(self._shown) == len(values) else [0.0] * len(values)) if animate else [0.0] * len(values)
        self._to = [0.12 + 0.88 * (v - lo) / span for v in values]
        self._hover = -1
        if animate:
            self._anim.stop()
            self._anim.start()
        else:
            self._shown = list(self._to)
            self.update()

    def _tick(self, t: float) -> None:
        self._shown = [a + (b - a) * t for a, b in zip(self._from, self._to)]
        self.update()

    def _geometry(self) -> tuple[float, float]:
        slot = self.width() / max(1, len(self._points))
        return slot, min(slot * 0.62, 16.0)

    def mouseMoveEvent(self, e) -> None:
        slot, _ = self._geometry()
        i = min(len(self._points) - 1, max(0, int(e.position().x() / slot))) if self._points else -1
        if i != self._hover:
            self._hover = i
            self.update()

    def leaveEvent(self, _e) -> None:
        self._hover = -1
        self.update()

    def paintEvent(self, _e) -> None:
        if not self._shown:
            return
        p = QPainter(self)
        setup(p)
        slot, bw = self._geometry()
        base, ceiling = float(self.height()), float(self.TOP)
        usable = base - ceiling
        n = len(self._shown)
        dark, light = QColor(theme.BAR), QColor(theme.BAR_LIGHT)

        for i, h in enumerate(self._shown):
            if i == self._hover:
                continue
            x = slot * i + (slot - bw) / 2
            height = max(bw, usable * h)
            p.setBrush(_mix(dark, light, i / max(1, n - 1)))
            p.setPen(Qt.PenStyle.NoPen)
            p.drawRoundedRect(QRectF(x, base - height, bw, height), bw / 2, bw / 2)

        if 0 <= self._hover < n:
            i = self._hover
            cx = slot * i + slot / 2
            height = max(bw, usable * self._shown[i])
            top = base - height
            line = QLinearGradient(0, 0, 0, top)
            line.setColorAt(0, QColor(255, 255, 255, 0))
            line.setColorAt(1, QColor(255, 255, 255, 90))
            p.setPen(QPen(line, 1.2))
            p.drawLine(QPointF(cx, 0), QPointF(cx, top))

            grad = QLinearGradient(0, top, 0, base)
            grad.setColorAt(0, QColor(theme.BLUE))
            grad.setColorAt(1, QColor("#7D96E8"))
            p.setBrush(grad)
            p.setPen(Qt.PenStyle.NoPen)
            p.drawRoundedRect(QRectF(cx - bw / 2, top, bw, height), bw / 2, bw / 2)
            p.setBrush(QColor("#F5F5F8"))
            p.setPen(QPen(QColor("#2B3F8C"), 2))
            p.drawEllipse(QPointF(cx, top), 5.5, 5.5)
            self._paint_tooltip(p, cx, top)

    def _paint_tooltip(self, p: QPainter, cx: float, top: float) -> None:
        day, value = self._points[self._hover]
        date_text, value_text = short_date(day, self._with_year), money(value)
        p.setFont(theme.font(14, W.Medium))
        fm = p.fontMetrics()
        w = fm.horizontalAdvance(date_text) + fm.horizontalAdvance(value_text) + 44
        h = 36.0
        x = cx - 16 - w
        if x < 0:
            x = cx + 16
        y = min(max(top - h / 2, 2), self.height() - h - 2)
        box = QRectF(x, y, w, h)
        p.setBrush(QColor(theme.TOOLTIP_BG))
        p.setPen(Qt.PenStyle.NoPen)
        p.drawRoundedRect(box, 10, 10)
        p.setPen(QColor(theme.MUTED))
        p.drawText(QRectF(x + 14, y, w, h), Qt.AlignmentFlag.AlignVCenter, date_text)
        sep = x + 14 + fm.horizontalAdvance(date_text) + 8
        p.setPen(QPen(QColor("#44444C"), 1))
        p.drawLine(QPointF(sep, y + 10), QPointF(sep, y + h - 10))
        p.setPen(QColor(theme.TEXT))
        p.drawText(QRectF(sep + 9, y, w, h), Qt.AlignmentFlag.AlignVCenter, value_text)


class TotalCard(Card):
    def __init__(self, store, parent=None):
        super().__init__(parent)
        self.store = store
        self.range_key = "1M"
        self.total = MoneyText(30)
        self.delta = DeltaLabel(13)
        self.chart = BarChart()

        pills = QHBoxLayout()
        pills.setSpacing(8)
        group = QButtonGroup(self)
        group.setExclusive(True)
        for key in RANGES:
            btn = PillButton(key, height=38, pad=17, px=15)
            btn.setChecked(key == self.range_key)
            btn.clicked.connect(lambda _=False, k=key: self.set_range(k))
            group.addButton(btn)
            pills.addWidget(btn)
        pills.addStretch()

        row = QHBoxLayout()
        row.setSpacing(8)
        row.addWidget(self.total)
        row.addWidget(self.delta, 0, Qt.AlignmentFlag.AlignBottom)
        row.addStretch()

        v = QVBoxLayout(self)
        v.setContentsMargins(22, 20, 22, 22)
        v.setSpacing(2)
        v.addWidget(Label("Saldo total", 14, W.Normal, theme.MUTED))
        v.addLayout(row)
        v.addSpacing(12)
        v.addLayout(pills)
        v.addSpacing(6)
        v.addWidget(self.chart, 1)
        store.changed.connect(lambda: self.refresh(animate=False))
        self.refresh(animate=False)

    def set_range(self, key: str) -> None:
        self.range_key = key
        self.refresh(animate=True)

    def refresh(self, animate: bool) -> None:
        points = self.store.history(self.range_key)
        first, last = points[0][1], points[-1][1]
        self.total.set_amount(last)
        self.delta.set_value((last / first - 1) * 100 if first else 0.0)
        self.chart.set_points(points, with_year=self.range_key in ("1A", "Tudo"), animate=animate)

