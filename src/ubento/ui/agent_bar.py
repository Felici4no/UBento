"""Faixa no topo da aba de um agente: estado do algoritmo e atalhos (rodar / configurar)."""

from __future__ import annotations

from PySide6.QtCore import QPointF, Qt, Signal
from PySide6.QtGui import QColor, QPainter
from PySide6.QtWidgets import QHBoxLayout, QWidget

from ..agent_config import MODES, RISK_LABELS, STRATEGIES
from ..workspace import Workspace
from . import theme
from .components import ActionButton, Label, setup
from .controls import Chip

W = theme.W


class _Dot(QWidget):
    def __init__(self, color: str, parent=None):
        super().__init__(parent)
        self._color = color
        self.setFixedSize(14, 28)

    def set_color(self, color: str) -> None:
        self._color = color
        self.update()

    def paintEvent(self, _e) -> None:
        p = QPainter(self)
        setup(p)
        p.setBrush(QColor(self._color))
        p.setPen(Qt.PenStyle.NoPen)
        p.drawEllipse(QPointF(7, 14), 6, 6)


class AgentBar(QWidget):
    run_requested = Signal()
    configure_requested = Signal()
    metas_requested = Signal()

    def __init__(self, workspace: Workspace, agent_id: str, parent=None):
        super().__init__(parent)
        self.ws, self.agent_id = workspace, agent_id
        self.setFixedHeight(48)
        self.dot = _Dot(theme.BLUE)
        self.name = Label("", 22, W.DemiBold)
        self.strategy, self.risk, self.mode, self.state, self.pending = Chip(), Chip(), Chip(), Chip(), Chip()
        self.run = ActionButton("Rodar agora", primary=True, height=38, pad=18)
        self.configure = ActionButton("Configurar", height=38, pad=18)
        self.metas = ActionButton("Metas", height=38, pad=18)
        self.metas.clicked.connect(self.metas_requested)
        self.run.clicked.connect(self.run_requested)
        self.configure.clicked.connect(self.configure_requested)

        h = QHBoxLayout(self)
        h.setContentsMargins(0, 0, 0, 0)
        h.setSpacing(8)
        h.addWidget(self.dot)
        h.addWidget(self.name)
        h.addSpacing(8)
        for chip in (self.strategy, self.risk, self.mode, self.state, self.pending):
            h.addWidget(chip)
        h.addStretch(1)
        h.addWidget(self.run)
        h.addWidget(self.metas)
        h.addWidget(self.configure)

        workspace.agent_changed.connect(lambda i: self.refresh() if i == agent_id else None)
        workspace.changed.connect(self.refresh)
        self.refresh()

    def refresh(self) -> None:
        agent = self.ws.agent(self.agent_id)
        if agent is None:
            return
        cfg = agent.config
        self.dot.set_color(agent.color)
        self.name.setText(agent.name)
        manual = cfg.strategy == "manual"
        self.strategy.set_chip(STRATEGIES[cfg.strategy][0])
        self.risk.set_chip(f"Risco {RISK_LABELS[cfg.risk].lower()}")
        self.risk.setVisible(cfg.relevant("risk"))
        self.mode.set_chip(MODES[cfg.mode][0])
        self.mode.setVisible(not manual)
        self.state.set_chip("Ativo" if cfg.active else "Pausado", theme.GREEN if cfg.active else theme.DIM)
        self.state.setVisible(not manual)
        count = self.ws.pending_count(self.agent_id)
        self.pending.set_chip(f"{count} {'pendente' if count == 1 else 'pendentes'}", theme.WARNING)
        self.pending.setVisible(count > 0)
        self.run.setEnabled(cfg.active and not manual)
        self.run.update()
