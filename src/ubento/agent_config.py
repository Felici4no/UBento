"""Configuração de um agente: qual algoritmo decide, com que risco, limites e modo de execução."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field, fields
from datetime import datetime, timedelta

# chave -> (nome, descrição curta)
STRATEGIES: dict[str, tuple[str, str]] = {
    "momentum": ("Tendência", "Compra ativos em alta e vende os que perdem força, com stop-loss e take-profit."),
    "rebalance": ("Rebalanceamento", "Mantém pesos iguais entre os ativos escolhidos, vendendo o que cresceu demais."),
    "dca": ("Média de custo", "Compra um valor fixo de forma recorrente, sem tentar acertar o preço."),
    "conservative": ("Conservador", "Prioriza caixa e reduz a exposição a cripto quando ela passa do limite."),
    "manual": ("Manual", "Não decide sozinho. Só você opera, pelo Swap."),
}
STRATEGY_ICONS = {"momentum": "trending-up", "rebalance": "repeat", "dca": "calendar", "conservative": "shield", "manual": "user"}

MODES: dict[str, tuple[str, str]] = {
    "auto": ("Automático", "Executa as decisões sozinho."),
    "approve": ("Pedir aprovação", "Propõe e espera você aprovar ou recusar."),
    "suggest": ("Só sugerir", "Registra sugestões, mas nunca executa."),
}
FREQUENCIES = {"hourly": "A cada hora", "daily": "Diária", "weekly": "Semanal"}
RISK_LABELS = {1: "Muito baixo", 2: "Baixo", 3: "Moderado", 4: "Alto", 5: "Muito alto"}
TRADABLE = ["ETH", "SOL", "AVAX", "BNB"]

# chave -> (mínimo, máximo, passo, sufixo, título, descrição)
PARAMS: dict[str, tuple[int, int, int, str, str, str]] = {
    "risk": (1, 5, 1, "", "Nível de risco", "Quanto maior, mais cedo o agente compra e maior o tamanho de cada operação."),
    "max_position_pct": (10, 100, 5, "%", "Posição máxima por ativo", "Nenhum ativo passa dessa fatia do patrimônio."),
    "reserve_pct": (0, 60, 5, "%", "Reserva mínima em caixa", "Parte do patrimônio que o agente nunca usa para comprar."),
    "trade_size_pct": (5, 50, 5, "%", "Tamanho de cada compra", "Fatia do caixa disponível usada em cada compra."),
    "stop_loss_pct": (2, 20, 1, "%", "Stop-loss", "Vende tudo de um ativo que cair mais que isso em 7 dias."),
    "take_profit_pct": (5, 40, 5, "%", "Take-profit", "Realiza lucro parcial de um ativo que subir mais que isso em 7 dias."),
    "rebalance_threshold_pct": (1, 20, 1, "%", "Desvio para rebalancear", "Só ajusta um ativo se ele fugir da meta por mais que isso."),
}
# quais parâmetros cada algoritmo usa (a tela só mostra os relevantes)
RELEVANT: dict[str, tuple[str, ...]] = {
    "manual": (),
    "conservative": ("risk", "reserve_pct"),
    "momentum": ("risk", "max_position_pct", "reserve_pct", "trade_size_pct", "stop_loss_pct", "take_profit_pct"),
    "rebalance": ("reserve_pct", "rebalance_threshold_pct"),
    "dca": ("reserve_pct", "trade_size_pct"),
}


@dataclass
class AgentConfig:
    strategy: str = "momentum"
    risk: int = 3
    mode: str = "approve"
    frequency: str = "daily"
    active: bool = True
    assets: list[str] = field(default_factory=lambda: list(TRADABLE))
    max_position_pct: int = 40
    reserve_pct: int = 20
    trade_size_pct: int = 25
    stop_loss_pct: int = 8
    take_profit_pct: int = 15
    rebalance_threshold_pct: int = 5
    last_run: str | None = None  # ISO 8601

    # -- (de)serialização ----------------------------------------------------

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict | None) -> AgentConfig:
        cfg = cls()
        for f in fields(cls):
            if data and f.name in data:
                setattr(cfg, f.name, data[f.name])
        return cfg.validated()

    def validated(self) -> AgentConfig:
        """Corrige valores fora do permitido (arquivo editado à mão, versão antiga…)."""
        if self.strategy not in STRATEGIES:
            self.strategy = "momentum"
        if self.mode not in MODES:
            self.mode = "approve"
        if self.frequency not in FREQUENCIES:
            self.frequency = "daily"
        for key, (lo, hi, _step, *_rest) in PARAMS.items():
            try:
                setattr(self, key, max(lo, min(hi, int(getattr(self, key)))))
            except (TypeError, ValueError):
                setattr(self, key, getattr(AgentConfig(), key))
        self.assets = [a for a in TRADABLE if a in (self.assets or [])] or list(TRADABLE)
        self.active = bool(self.active)
        return self

    def relevant(self, key: str) -> bool:
        return key in RELEVANT[self.strategy]


def describe(cfg: AgentConfig) -> str:
    """Resumo em uma frase de como o agente vai se comportar."""
    name = STRATEGIES[cfg.strategy][0]
    if cfg.strategy == "manual":
        return "Modo manual: este agente não toma decisões sozinho. Todas as operações partem de você."
    parts = [f"Estratégia {name.lower()}"]
    if cfg.relevant("risk"):
        parts.append(f"risco {RISK_LABELS[cfg.risk].lower()} ({cfg.risk}/5)")
    parts.append(f"opera {', '.join(cfg.assets)}")
    parts.append(f"mantém {cfg.reserve_pct}% em caixa")
    if cfg.relevant("trade_size_pct"):
        parts.append(f"usa {cfg.trade_size_pct}% do caixa em cada compra")
    if cfg.relevant("max_position_pct"):
        parts.append(f"limita cada ativo a {cfg.max_position_pct}% do patrimônio")
    if cfg.relevant("stop_loss_pct"):
        parts.append(f"stop-loss de {cfg.stop_loss_pct}% e take-profit de {cfg.take_profit_pct}%")
    if cfg.relevant("rebalance_threshold_pct"):
        parts.append(f"rebalanceia com desvio acima de {cfg.rebalance_threshold_pct}%")
    mode = {"auto": "executa sozinho", "approve": "pede a sua aprovação antes de executar", "suggest": "apenas sugere, sem executar"}[cfg.mode]
    when = FREQUENCIES[cfg.frequency].lower()
    status = "" if cfg.active else " (agente pausado)"
    return f"{'; '.join(parts)}. Ele {mode} e roda {when}.{status}"


def next_run(cfg: AgentConfig, now: datetime) -> datetime:
    if cfg.frequency == "hourly":
        return now.replace(minute=0, second=0, microsecond=0) + timedelta(hours=1)
    base = now.replace(hour=9, minute=0, second=0, microsecond=0)
    if cfg.frequency == "daily":
        return base if base > now else base + timedelta(days=1)
    days = (7 - now.weekday()) % 7  # próxima segunda-feira às 9h
    candidate = base + timedelta(days=days)
    return candidate if candidate > now else candidate + timedelta(days=7)
