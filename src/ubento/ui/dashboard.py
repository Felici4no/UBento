"""Painel de cards de um agente (ou do agregado "Geral")."""

from __future__ import annotations

from PySide6.QtCore import Signal
from PySide6.QtWidgets import QHBoxLayout, QVBoxLayout, QWidget

from ..store import Store
from .cards import ActivityCard, CoinCard, CryptoCard, ExchangeCard, SummaryCard, TotalCard, TransfersCard

GAP = 20
NATURAL_HEIGHT = 944 + 56  # cards do modelo + margens; abaixo disso a página rola
NATURAL_WIDTH = 900


class Dashboard(QWidget):
    notify = Signal(str, bool)

    def __init__(self, store: Store, parent=None):
        super().__init__(parent)
        self.store = store
        self.setMinimumSize(NATURAL_WIDTH, NATURAL_HEIGHT)

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
        grid.setContentsMargins(0, 0, 0, 0)
        grid.addLayout(left, 1)
        grid.addLayout(right, 1)

        holder = QWidget()
        holder.setMaximumWidth(960)
        holder.setLayout(grid)

        outer = QHBoxLayout(self)
        outer.setContentsMargins(32, 8, 32, 28)
        outer.addStretch(1)
        outer.addWidget(holder, 100)
        outer.addStretch(1)

        self.exchange.notify.connect(self.notify)
        self.coin.buy_clicked.connect(lambda: self.exchange.prefill("USD", "USDC"))
        self.coin.receive_clicked.connect(lambda: self.notify.emit("Receber USDC estará disponível em breve", True))
