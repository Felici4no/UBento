"""Painel de cards de um agente — ou, na aba Geral, a visão consolidada."""

from __future__ import annotations

from PySide6.QtCore import Signal
from PySide6.QtWidgets import QHBoxLayout, QVBoxLayout, QWidget

from ..store import Store
from ..workspace import Agent, Workspace
from .agent_bar import AgentBar
from .cards import ActivityCard, AgentsCard, CoinCard, CryptoCard, DecisionsCard, ExchangeCard, SummaryCard, TotalCard

GAP = 20
NATURAL_HEIGHT = 944 + 56  # cards do modelo + margens; abaixo disso a página rola
NATURAL_WIDTH = 900


class Dashboard(QWidget):
    notify = Signal(str, bool)
    open_agent = Signal(str)
    expand_requested = Signal(str, object)  # (tipo do card, widget do card)
    configure_requested = Signal(str)  # id do agente
    metas_requested = Signal(str)  # id do agente

    def __init__(self, store: Store, workspace: Workspace, agent: Agent | None = None, parent=None):
        """Sem `agent`, vira a aba Geral: o card Agentes ocupa o lugar do Swap."""
        super().__init__(parent)
        self.store, self.workspace, self.agent = store, workspace, agent
        overview = agent is None
        self.setMinimumSize(NATURAL_WIDTH, NATURAL_HEIGHT + (0 if overview else 64))

        def lookup(agent_id: str):
            found = workspace.agent(agent_id)
            return (found.name, found.color) if found else None

        self.crypto = CryptoCard(store)
        self.total = TotalCard(store)
        self.summary = SummaryCard(store)
        self.activity = ActivityCard(store)
        self.decisions = DecisionsCard(store, lookup if overview else None)
        self.coin = CoinCard(store)
        self.exchange: ExchangeCard | None = None
        self.agents: AgentsCard | None = None
        self.bar: AgentBar | None = None
        self.decisions.resolve_requested.connect(self.resolve_decision)
        self.decisions.registrar_requested.connect(self.solicitar_registro)

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
            self.bar = AgentBar(workspace, agent.id)
            self.bar.run_requested.connect(self._run_agent)
            self.bar.configure_requested.connect(lambda: self.configure_requested.emit(agent.id))
            self.bar.metas_requested.connect(lambda: self.metas_requested.emit(agent.id))
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
        column = QVBoxLayout(holder)
        column.setContentsMargins(0, 0, 0, 0)
        column.setSpacing(16)
        if self.bar:
            column.addWidget(self.bar)
        column.addLayout(grid, 1)

        outer = QHBoxLayout(self)
        outer.setContentsMargins(32, 8, 32, 28)
        outer.addStretch(1)
        outer.addWidget(holder, 100)
        outer.addStretch(1)

    # -- ações dos agentes ----------------------------------------------------

    def _run_agent(self) -> None:
        made, message = self.workspace.run_agent(self.agent.id)
        self.notify.emit(message, made > 0)

    def resolve_decision(self, uid: str, approve: bool) -> None:
        """✓ aprova, ✕ recusa. Aprovar NÃO executa: a execução é registrada à parte."""
        error = self.workspace.resolve_decision(uid, approve)
        self.notify.emit(error or ("Aprovada. Falta registrar a execução depois que ela acontecer" if approve else "Proposta recusada"), error is None)

    def solicitar_registro(self, uid: str) -> None:
        """Pede confirmação explícita antes de registrar que a operação foi executada."""
        from PySide6.QtWidgets import QMessageBox

        box = QMessageBox(QMessageBox.Icon.Question, "Registrar execução", "Confirma que esta operação foi executada?", parent=self)
        box.setInformativeText("Só registre depois de a execução estar confirmada. Isto atualiza os saldos; aprovar sozinho não faz isso.")
        sim = box.addButton("Registrar execução", QMessageBox.ButtonRole.AcceptRole)
        box.addButton("Cancelar", QMessageBox.ButtonRole.RejectRole)
        box.exec()
        if box.clickedButton() is sim:
            self.registrar_execucao(uid)

    def registrar_execucao(self, uid: str) -> None:
        error = self.workspace.registrar_execucao(uid)
        self.notify.emit(error or "Execução registrada", error is None)
