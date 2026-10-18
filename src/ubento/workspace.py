"""Agentes (carteiras) do usuário e a aba "Geral" que soma todos eles.

A configuração (nome, cor, ordem) persiste em QSettings; os saldos ainda são de
demonstração e não persistem.
"""

from __future__ import annotations

import json
import random
from dataclasses import dataclass, field

from PySide6.QtCore import QObject, QSettings, Signal

from .store import Store

OVERVIEW = "overview"
COLORS = ["#3B6BFF", "#B14CF0", "#2EE081", "#F2B01E", "#EF4B3F", "#2FC6E8", "#F26FB1"]


@dataclass
class Agent:
    id: str
    name: str
    color: str
    seed: str
    scale: float
    store: Store = field(repr=False, default=None)  # type: ignore[assignment]


class Workspace(QObject):
    changed = Signal()

    def __init__(self, settings: QSettings | None = None) -> None:
        super().__init__()
        self._settings = settings
        self.overview_name = "Geral"
        self.agents: list[Agent] = []
        self.overview = Store.combined([])
        if not self._load():
            self.agents = [self._make("Pessoal", COLORS[0], "main", 1.0), self._make("Empresa", COLORS[1], "empresa", 2.6)]
        self._refresh_overview()

    # -- consulta ----------------------------------------------------------

    def agent(self, agent_id: str) -> Agent | None:
        return next((a for a in self.agents if a.id == agent_id), None)

    def index(self, agent_id: str) -> int:
        return next(i for i, a in enumerate(self.agents) if a.id == agent_id)

    # -- edição ------------------------------------------------------------

    def add(self, name: str | None = None) -> Agent:
        n = len(self.agents) + 1
        seed = f"agente-{random.Random().randrange(10**6)}"
        agent = self._make(name or f"Agente {n}", COLORS[(n - 1) % len(COLORS)], seed, random.Random(seed).uniform(0.4, 2.2))
        self.agents.append(agent)
        self._commit()
        return agent

    def duplicate(self, agent_id: str) -> Agent | None:
        src = self.agent(agent_id)
        if src is None:
            return None
        copy = self._make(f"{src.name} (cópia)", src.color, src.seed, src.scale)
        copy.store.holdings = dict(src.store.holdings)
        copy.store.transfers = list(src.store.transfers)
        self.agents.insert(self.index(agent_id) + 1, copy)
        self._commit()
        return copy

    def remove(self, agent_id: str) -> None:
        self.agents = [a for a in self.agents if a.id != agent_id]
        self._commit()

    def rename(self, key: str, name: str) -> None:
        name = name.strip()
        if not name:
            return
        if key == OVERVIEW:
            self.overview_name = name
        elif (agent := self.agent(key)):
            agent.name = name
        self._commit(rebuild=False)

    def recolor(self, agent_id: str, color: str) -> None:
        if (agent := self.agent(agent_id)):
            agent.color = color
            self._commit(rebuild=False)

    def move_to(self, agent_id: str, new_index: int) -> None:
        agent = self.agent(agent_id)
        if agent is None:
            return
        self.agents.remove(agent)
        self.agents.insert(max(0, min(new_index, len(self.agents))), agent)
        self._commit(rebuild=False)

    # -- interno -----------------------------------------------------------

    def _make(self, name: str, color: str, seed: str, scale: float) -> Agent:
        agent_id = f"a{random.Random().randrange(16**8):08x}"
        return Agent(agent_id, name, color, seed, scale, Store(seed=seed, scale=scale))

    def _refresh_overview(self) -> None:
        self.overview.set_parts([a.store for a in self.agents])

    def _commit(self, rebuild: bool = True) -> None:
        if rebuild:
            self._refresh_overview()
        self._save()
        self.changed.emit()

    def _save(self) -> None:
        if self._settings is None:
            return
        data = {
            "overview_name": self.overview_name,
            "agents": [{"id": a.id, "name": a.name, "color": a.color, "seed": a.seed, "scale": a.scale} for a in self.agents],
        }
        self._settings.setValue("workspace", json.dumps(data))
        self._settings.sync()

    def _load(self) -> bool:
        if self._settings is None:
            return False
        raw = self._settings.value("workspace")
        try:
            data = json.loads(raw) if raw else None
            if not data or not data["agents"]:
                return False
            self.overview_name = data.get("overview_name", "Geral")
            self.agents = [
                Agent(d["id"], d["name"], d["color"], d["seed"], float(d["scale"]), Store(seed=d["seed"], scale=float(d["scale"])))
                for d in data["agents"]
            ]
            return True
        except (ValueError, KeyError, TypeError):
            return False
