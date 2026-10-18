"""Janela principal: grade de cards sobre fundo escuro."""

from __future__ import annotations

from PySide6.QtCore import QRectF, Qt
from PySide6.QtGui import QColor, QLinearGradient, QPainter
from PySide6.QtWidgets import QFrame, QHBoxLayout, QMainWindow, QScrollArea, QVBoxLayout, QWidget

from ..store import Store
from . import theme
from .cards import ActivityCard, CoinCard, CryptoCard, ExchangeCard, SummaryCard, TotalCard, TransfersCard
from .components import Toast

GAP = 20
NATURAL_HEIGHT = 1010  # altura da composição do modelo (944 de cards + margens)


class _Canvas(QWidget):
    def paintEvent(self, _e) -> None:
        p = QPainter(self)
        g = QLinearGradient(0, 0, 0, self.height())
        g.setColorAt(0, QColor(theme.BG_TOP))
        g.setColorAt(1, QColor(theme.BG_BOTTOM))
        p.fillRect(QRectF(self.rect()), g)


class MainWindow(QMainWindow):
    def __init__(self, store: Store):
        super().__init__()
        self.setWindowTitle("UBento")
        self.setMinimumSize(760, 520)
        available = self.screen().availableGeometry() if self.screen() else None
        self.resize(980, min(1020, (available.height() - 40) if available else 1020))

        self.store = store
        canvas = _Canvas()
        canvas.setMinimumSize(900, NATURAL_HEIGHT)  # abaixo disso a janela rola em vez de espremer os cards
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        scroll.setWidget(canvas)
        self.setCentralWidget(scroll)

        self.crypto = CryptoCard(store)
        self.total = TotalCard(store)
        self.summary = SummaryCard(store)
        self.activity = ActivityCard(store)
        self.exchange = ExchangeCard(store)
        self.transfers = TransfersCard(store)
        self.coin = CoinCard(store)

        mid = QHBoxLayout()
        mid.setSpacing(GAP)
        mid.addWidget(self.summary, 1)
        mid.addWidget(self.activity, 1)

        left = QVBoxLayout()
        left.setSpacing(GAP)
        left.addWidget(self.crypto, 182)
        left.addLayout(mid, 252)
        left.addWidget(self.exchange, 470)

        right = QVBoxLayout()
        right.setSpacing(GAP)
        right.addWidget(self.total, 454)
        right.addWidget(self.transfers, 267)
        right.addWidget(self.coin, 183)

        grid = QHBoxLayout()
        grid.setSpacing(GAP)
        grid.addLayout(left, 1)
        grid.addLayout(right, 1)

        holder = QWidget()
        holder.setMaximumWidth(960)
        holder.setLayout(grid)
        grid.setContentsMargins(0, 0, 0, 0)

        outer = QHBoxLayout(canvas)
        outer.setContentsMargins(32, 28, 32, 28)
        outer.addStretch(1)
        outer.addWidget(holder, 100)
        outer.addStretch(1)

        self.toast = Toast(scroll)
        self.exchange.notify.connect(self.toast.show_message)
        self.coin.buy_clicked.connect(lambda: self.exchange.prefill("USD", "USDC"))
        self.coin.receive_clicked.connect(lambda: self.toast.show_message("Receber USDC estará disponível em breve", True))

    def resizeEvent(self, e) -> None:
        super().resizeEvent(e)
        self.toast.reposition()
