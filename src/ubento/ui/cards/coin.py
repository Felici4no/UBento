"""Card da moeda (USDC): saldo, atalhos e minigráfico de cotação."""

from __future__ import annotations

from PySide6.QtCore import QPointF, QRectF, Qt, Signal
from PySide6.QtGui import QColor, QLinearGradient, QPainter, QPainterPath, QPen
from PySide6.QtWidgets import QHBoxLayout, QVBoxLayout, QWidget

from ...formatting import money, number, pct
from ...store import ASSETS, Store
from .. import theme
from ..components import Card, Label, RoundButton, setup

W = theme.W
SYMBOL = "USDC"


class Sparkline(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self._values: list[float] = []
        self._hover = -1
        self.setMouseTracking(True)
        self.setMinimumHeight(54)

    def set_values(self, values: list[float]) -> None:
        self._values = values
        self.update()

    def _xy(self, i: int) -> QPointF:
        lo, hi = min(self._values), max(self._values)
        span = (hi - lo) or 1e-9
        x = self.width() * i / (len(self._values) - 1)
        y = 6 + (self.height() - 12) * (1 - (self._values[i] - lo) / span)
        return QPointF(x, y)

    def mouseMoveEvent(self, e) -> None:
        if self._values:
            self._hover = round(e.position().x() / self.width() * (len(self._values) - 1))
            self._hover = min(len(self._values) - 1, max(0, self._hover))
            self.update()

    def leaveEvent(self, _e) -> None:
        self._hover = -1
        self.update()

    def paintEvent(self, _e) -> None:
        if len(self._values) < 2:
            return
        p = QPainter(self)
        setup(p)
        down = self._values[-1] < self._values[0]
        base = QColor(theme.RED if down else theme.GREEN)
        pts = [self._xy(i) for i in range(len(self._values))]
        line = QPainterPath(pts[0])
        for pt in pts[1:]:
            line.lineTo(pt)
        area = QPainterPath(line)
        area.lineTo(pts[-1].x(), self.height())
        area.lineTo(pts[0].x(), self.height())
        area.closeSubpath()
        grad = QLinearGradient(0, 0, 0, self.height())
        top = QColor(base)
        top.setAlpha(120)
        bottom = QColor(base)
        bottom.setAlpha(0)
        grad.setColorAt(0, top)
        grad.setColorAt(1, bottom)
        p.fillPath(area, grad)
        stroke = QColor(base)
        stroke.setAlpha(210)
        p.setPen(QPen(stroke, 1.6, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap, Qt.PenJoinStyle.RoundJoin))
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.drawPath(line)

        if self._hover >= 0:
            pt = pts[self._hover]
            p.setPen(QPen(QColor(255, 255, 255, 50), 1))
            p.drawLine(QPointF(pt.x(), 0), QPointF(pt.x(), self.height()))
            p.setBrush(QColor("#F5F5F8"))
            p.setPen(QPen(base, 2))
            p.drawEllipse(pt, 4, 4)
            text = f"1 USDC = ${number(self._values[self._hover], 4)}"
            p.setFont(theme.font(12, W.Medium))
            w = p.fontMetrics().horizontalAdvance(text) + 18
            x = min(max(pt.x() - w / 2, 0), self.width() - w)
            box = QRectF(x, 0, w, 24)
            p.setBrush(QColor(theme.TOOLTIP_BG))
            p.setPen(Qt.PenStyle.NoPen)
            p.drawRoundedRect(box, 8, 8)
            p.setPen(QColor(theme.TEXT))
            p.drawText(box, Qt.AlignmentFlag.AlignCenter, text)


class _CoinBadge(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedSize(46, 46)

    def paintEvent(self, _e) -> None:
        p = QPainter(self)
        setup(p)
        p.setBrush(QColor(theme.ASSET_COLORS[SYMBOL]))
        p.setPen(Qt.PenStyle.NoPen)
        p.drawEllipse(QRectF(self.rect()))
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.setPen(QPen(QColor("white"), 2))
        p.drawEllipse(QRectF(self.rect()).adjusted(8, 8, -8, -8))
        p.setFont(theme.font(17, W.Bold))
        p.drawText(QRectF(self.rect()), Qt.AlignmentFlag.AlignCenter, "$")


class CoinCard(Card):
    receive_clicked = Signal()
    buy_clicked = Signal()

    def __init__(self, store: Store, parent=None):
        super().__init__(parent)
        self.store = store
        self.value = Label("", 24, W.DemiBold)
        self.units = Label("", 14, W.Normal, theme.MUTED)
        self.spark = Sparkline()
        self.footer_rate = Label("", 13, W.Medium)
        self.footer_delta = Label("", 13, W.Medium, theme.RED)
        receive = RoundButton("arrow-down-left", size=46, icon_size=18, bg="#1B1B20")
        buy = RoundButton("plus", size=46, icon_size=20, bg=theme.BLUE, stroke=2.2)
        receive.clicked.connect(self.receive_clicked)
        buy.clicked.connect(self.buy_clicked)
        receive.setToolTip("Receber USDC")
        buy.setToolTip("Comprar USDC")

        texts = QVBoxLayout()
        texts.setSpacing(0)
        texts.addWidget(self.value)
        texts.addWidget(self.units)

        head = QHBoxLayout()
        head.setSpacing(14)
        head.addWidget(_CoinBadge())
        head.addLayout(texts)
        head.addStretch()
        head.addWidget(receive)
        head.addWidget(buy)

        foot = QHBoxLayout()
        foot.setSpacing(10)
        foot.addWidget(Label("USD Coin", 13, W.Medium, theme.TEXT))
        foot.addStretch()
        foot.addWidget(self.footer_rate)
        foot.addWidget(self.footer_delta)

        v = QVBoxLayout(self)
        v.setContentsMargins(20, 18, 20, 16)
        v.setSpacing(0)
        v.addLayout(head)
        v.addSpacing(6)
        v.addWidget(self.spark, 1)
        v.addSpacing(4)
        v.addLayout(foot)
        store.changed.connect(self.refresh)
        self.refresh()

    def refresh(self) -> None:
        held = self.store.holdings.get(SYMBOL, 0.0)
        price = ASSETS[SYMBOL].price
        series = self.store.usdc_series()
        change = (series[-1] / series[0] - 1) * 100
        self.value.setText(money(held * price))
        self.units.setText(f"{number(held, 2)} {SYMBOL}")
        self.spark.set_values(series)
        self.footer_rate.setText(f"1 USDC = ${number(price, 3)}   |")
        self.footer_delta.setText(f"{pct(change)} {'↓' if change < 0 else '↑'}")
        self.footer_delta.set_color(theme.RED if change < 0 else theme.GREEN)
