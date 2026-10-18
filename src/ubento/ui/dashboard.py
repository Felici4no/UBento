"""Painel de cards de um agente — ou, na aba Geral, a visão consolidada."""

from __future__ import annotations

from PySide6.QtCore import Signal
from PySide6.QtWidgets import QHBoxLayout, QVBoxLayout, QWidget

from ..store import Store
from ..workspace import Workspace
from .cards import ActivityCard, AgentsCard, CoinCard, CryptoCard, DecisionsCard, ExchangeCard, SummaryCard, TotalCard

GAP = 20
NATURAL_HEIGHT = 944 + 56  # cards do modelo + margens; abaixo disso a página rola
NATURAL_WIDTH = 900


class Dashboard(QWidget):
    notify = Signal(str, bool)
    open_agent = Signal(str)
    expand_requested = Signal(str, object)  # (tipo do card, widget do card)

    def __init__(self, store: Store, workspace: Workspace | None = None, parent=None):
        """Com `workspace`, vira a aba Geral: o card Agentes ocupa o lugar do Swap."""
        super().__init__(parent)
        self.store = store
        self.setMinimumSize(NATURAL_WIDTH, NATURAL_HEIGHT)
        overview = workspace is not None

        def lookup(agent_id: str):
            agent = workspace.agent(agent_id) if workspace else None
            return (agent.name, agent.color) if agent else None

        self.crypto = CryptoCard(store)
        self.total = TotalCard(store)
        self.summary = SummaryCard(store)
        self.activity = ActivityCard(store)
        self.decisions = DecisionsCard(store, lookup if overview else None)
        self.coin = CoinCard(store)
        self.exchange: ExchangeCard | None = None
        self.agents: AgentsCard | None = None

        if overview:
            self.agents = AgentsCard(workspace)
            self.agents.agent_clicked.connect(self.open_agent)
            self.total.range_changed.connect(self.agents.set_range)
            workspace.changed.connect(self.agents.refresh)
            workspace.changed.connect(self.decisions.refresh)
            store.changed.connect(self.agents.refresh)
            bottom_left = self.agents
            self.coin.buy_clicked.connect(lambda: self.notify.emit("Escolha um agente para comprar USDC", False))
        else:
            self.exchange = ExchangeCard(store)
            self.exchange.notify.connect(self.notify)
            bottom_left = self.exchange
            self.coin.buy_clicked.connect(lambda: self.exchange.prefill("USD", "USDC"))
        self.coin.receive_clicked.connect(lambda: self.notify.emit("Receber USDC estará disponível em breve", True))

        expandable = {"crypto": self.crypto, "total": self.total, "summary": self.summary, "activity": self.activity,
                      "decisions": self.decisions, "coin": self.coin}
        if self.agents:
            expandable["agents"] = self.agents
        for kind, card in expandable.items():
            card.make_expandable()
            card.expand_requested.connect(lambda k=kind, c=card: self.expand_requested.emit(k, c))

        mid = QHBoxLayout()
        mid.setSpacing(GAP)
        mid.addWidget(self.summary, 1)
        mid.addWidget(self.activity, 1)

        left = QVBoxLayout()
        left.setSpacing(GAP)
        left.addWidget(self.crypto, 182)
        left.addLayout(mid, 252)
        left.addWidget(bottom_left, 470)

        right = QVBoxLayout()
        right.setSpacing(GAP)
        right.addWidget(self.total, 454)
        right.addWidget(self.decisions, 267)
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
