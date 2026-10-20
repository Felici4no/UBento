"""Agentes (carteiras) do usuário e a aba "Geral" que soma todos eles.

A configuração (nome, cor, ordem) persiste em QSettings; os saldos ainda são de
demonstração e não persistem.
"""

from __future__ import annotations

import json
import random
from collections.abc import Callable
from dataclasses import dataclass, field, replace
from datetime import datetime

from PySide6.QtCore import QObject, QSettings, Signal

from . import engine, formatting
from .agent_config import AgentConfig
from .cotacoes import Cotacoes
from .mercado import AGUARDANDO_PRECOS, Mercado
from .store import RANGES, Store

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
    config: AgentConfig = field(default_factory=AgentConfig)


DEFAULT_PREFS = {"user_name": "Você", "hide_values": False, "default_range": "1M", "mercado": "simulado"}


class Workspace(QObject):
    changed = Signal()  # estrutura ou aparência dos agentes mudou
    agent_changed = Signal(str)  # configuração de um agente mudou (id)
    prefs_changed = Signal()
    mercado_changed = Signal()  # chegou uma leitura (ou uma falha) do mercado real
    decisao_executada = Signal(str, object)  # (id do agente, decisão): uma decisão com movimento foi executada

    def __init__(self, settings: QSettings | None = None, relogio: Callable[[], datetime] = datetime.now) -> None:
        super().__init__()
        self.mercado = Mercado(relogio)  # preços, sinais e relógio: um por Workspace, entregue a todas as carteiras
        self._settings = settings
        self.prefs: dict = dict(DEFAULT_PREFS)
        self.overview_name = "Geral"
        self.agents: list[Agent] = []
        self.overview = Store.combined([], mercado=self.mercado)
        if not self._load():
            self.agents = self._default_agents()
            self._save()  # os ids são aleatórios: sem gravar já na 1ª execução, as metas ficariam órfãs depois de reiniciar
        self._refresh_overview()
        formatting.set_hidden(bool(self.prefs["hide_values"]))
        self.overview.real = self.mercado_real
        if self.mercado_real:
            self.mercado.ligar()
            self.overview.definir_modo(True)

    # -- preferências ------------------------------------------------------

    def pref(self, key: str):
        return self.prefs[key]

    def set_pref(self, key: str, value) -> None:
        if key not in DEFAULT_PREFS or self.prefs.get(key) == value:
            return
        if key == "default_range" and value not in RANGES:
            return
        if key == "mercado" and value not in ("simulado", "real"):
            return
        self.prefs[key] = value
        if key == "hide_values":
            formatting.set_hidden(bool(value))
            self._repaint_all()
        if key == "mercado":
            self._trocar_mercado(value == "real")
        self._save()
        self.prefs_changed.emit()

    # -- mercado real --------------------------------------------------------

    @property
    def mercado_real(self) -> bool:
        return self.prefs["mercado"] == "real"

    def _trocar_mercado(self, real: bool) -> None:
        """Liga/desliga o mercado real. Cada carteira recomeça no modo novo (nova com caixa, ou a demonstração) e o Geral acompanha."""
        self.mercado.ligar() if real else self.mercado.desativar()
        for agent in self.agents:
            agent.store.definir_modo(real)
        self.overview.real = real
        self.overview.definir_modo(real)
        self.mercado_changed.emit()

    def receber_cotacoes(self, cotacoes: Cotacoes, agora: datetime | None = None) -> None:
        """Entra uma leitura nova da Binance: preços, sinais e um ponto no histórico de cada carteira. Ignora leituras atrasadas após desligar o modo."""
        if not self.mercado_real:
            return
        agora = agora or self.mercado.agora()
        self.mercado.aplicar(cotacoes.precos, cotacoes.variacao_7d, agora)
        for agent in self.agents:
            agent.store.registrar_ponto(agora)
            agent.store.changed.emit()  # o Geral se recalcula por aqui
        self.overview.registrar_ponto(agora)
        self.overview.changed.emit()
        self.mercado_changed.emit()

    def receber_falha(self, mensagem: str) -> None:
        """A leitura falhou: o último preço continua valendo (até vencer) e a tela passa a mostrar o motivo."""
        if self.mercado_real:
            self.mercado.erro = mensagem
            self.mercado_changed.emit()

    def status_mercado(self, agora: datetime | None = None) -> str:
        if not self.mercado_real:
            return "Dados simulados de demonstração."
        agora = agora or self.mercado.agora()
        if self.mercado.erro:
            return f"Sem preços novos: {self.mercado.erro}"
        if self.mercado.atualizado_em is None:
            return "Buscando os preços na Binance…"
        if not self.mercado.fresco(agora):
            return f"Preços desatualizados (última leitura às {self.mercado.atualizado_em:%H:%M:%S})."
        return f"Preços ao vivo da Binance · última leitura às {self.mercado.atualizado_em:%H:%M:%S}"

    def _repaint_all(self) -> None:
        """Força todos os cards a reler os valores (necessário ao mascarar/desmascarar)."""
        for agent in self.agents:
            agent.store.changed.emit()

    # -- dados -------------------------------------------------------------

    def reset_demo_data(self) -> None:
        """Restaura os saldos e decisões de demonstração, mantendo nomes, cores e ordem."""
        for agent in self.agents:
            agent.store.reset()

    def restore_default_agents(self) -> None:
        """Volta ao conjunto inicial de agentes."""
        self.agents = self._default_agents()
        self.overview_name = "Geral"
        self._commit()

    def _default_agents(self) -> list[Agent]:
        personal = self._make("Pessoal", COLORS[0], "main", 1.0)
        company = self._make("Empresa", COLORS[1], "empresa", 2.6)
        company.config = AgentConfig(strategy="rebalance", mode="auto", frequency="weekly", reserve_pct=25)
        return [personal, company]

    # -- configuração e execução dos agentes --------------------------------

    def set_config(self, agent_id: str, **changes) -> None:
        agent = self.agent(agent_id)
        if agent is None:
            return
        for key, value in changes.items():
            if not hasattr(agent.config, key):
                raise AttributeError(key)
            setattr(agent.config, key, value)
        agent.config.validated()
        self._save()
        self.agent_changed.emit(agent_id)

    def reset_config(self, agent_id: str) -> None:
        agent = self.agent(agent_id)
        if agent is not None:
            agent.config = AgentConfig()
            self._save()
            self.agent_changed.emit(agent_id)

    def run_agent(self, agent_id: str, now: datetime | None = None) -> tuple[int, str]:
        """Roda o algoritmo do agente. Devolve (decisões geradas, mensagem para o usuário)."""
        agent = self.agent(agent_id)
        if agent is None:
            return 0, ""
        cfg = agent.config
        if cfg.strategy == "manual":
            return 0, "Este agente é manual: não toma decisões sozinho"
        if not cfg.active:
            return 0, "Agente pausado. Ative-o para rodar"
        now = now or self.mercado.agora()
        if agent.store.real and not self.mercado.fresco(now):
            return 0, AGUARDANDO_PRECOS
        status = {"auto": "executed", "approve": "proposed", "suggest": "suggested"}[cfg.mode]
        made = 0
        for d in engine.decide(cfg, agent.store, now):
            if d.trade is None:  # "manteve…" não precisa de aprovação
                agent.store.add_decision(d)
            elif agent.store.add_decision(replace(d, status=status)) is not None:
                continue  # sem saldo: descarta
            made += 1
        cfg.last_run = now.isoformat(timespec="seconds")
        self._save()
        self.agent_changed.emit(agent_id)
        text = {
            "auto": f"{made} decisões executadas",
            "approve": f"{made} propostas aguardando você",
            "suggest": f"{made} sugestões registradas",
        }[cfg.mode]
        return made, text

    def resolve_decision(self, uid: str, approve: bool) -> str | None:
        """Aprova/recusa uma proposta, onde quer que ela esteja (inclusive vista pelo Geral)."""
        for agent in self.agents:
            if any(d.uid == uid for d in agent.store.decisions):
                error = agent.store.resolve_decision(uid, approve)
                self.agent_changed.emit(agent.id)
                return error
        return "Proposta não encontrada"

    def registrar_execucao(self, uid: str) -> str | None:
        """Registra a execução de uma decisão aprovada (passo SEPARADO da aprovação)."""
        for agent in self.agents:
            if any(d.uid == uid for d in agent.store.decisions):
                error = agent.store.registrar_execucao(uid)
                self.agent_changed.emit(agent.id)
                return error
        return "Decisão não encontrada"

    def pending_count(self, agent_id: str | None = None) -> int:
        """Decisões que esperam uma ação sua: aprovar/recusar (propostas) ou registrar a execução (aprovadas)."""
        agents = [a for a in self.agents if agent_id in (None, a.id)]
        return sum(1 for a in agents for d in a.store.decisions if d.status in ("proposed", "approved"))

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
        copy.store.decisions = list(src.store.decisions)
        copy.config = AgentConfig.from_dict(src.config.to_dict())
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
        return Agent(agent_id, name, color, seed, scale, self._store(agent_id, seed, scale))

    def _store(self, agent_id: str, seed: str, scale: float) -> Store:
        real = self.mercado_real
        store = Store(seed=seed, scale=scale, real=real, mercado=self.mercado)
        store.owner_id = agent_id
        store.executed.connect(lambda decisao, agente=agent_id: self.decisao_executada.emit(agente, decisao))
        return store

    def performance(self, agent: Agent, range_key: str) -> tuple[float, float]:
        """(variação %, variação em USD) do patrimônio do agente no período."""
        series = agent.store.history(range_key)
        first, last = series[0][1], series[-1][1]
        return ((last / first - 1) * 100 if first else 0.0), last - first

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
            "prefs": self.prefs,
            "agents": [{"id": a.id, "name": a.name, "color": a.color, "seed": a.seed, "scale": a.scale, "config": a.config.to_dict()} for a in self.agents],
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
            self.prefs.update({k: v for k, v in data.get("prefs", {}).items() if k in DEFAULT_PREFS})
            self.agents = [
                Agent(d["id"], d["name"], d["color"], d["seed"], float(d["scale"]), self._store(d["id"], d["seed"], float(d["scale"])),
                      AgentConfig.from_dict(d.get("config")))
                for d in data["agents"]
            ]
            return True
        except (ValueError, KeyError, TypeError):
            return False
