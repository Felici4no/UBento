"""Estado do app em memória, com dados de demonstração.

Por enquanto só interface: nada aqui persiste. A camada SQLite entra depois,
mantendo esta mesma API (`Store`) para as telas.
"""

from __future__ import annotations

import calendar
import math
import random
from dataclasses import dataclass, replace
from datetime import date, datetime, timedelta

from PySide6.QtCore import QObject, Signal

SERVICE_FEE_RATE = 0.023
GAS_FEE_USD = 1.32


@dataclass(frozen=True)
class Asset:
    symbol: str
    name: str
    price: float  # em USD
    decimals: int


ASSETS: dict[str, Asset] = {
    a.symbol: a
    for a in (
        Asset("USD", "Dólar", 1.0, 2),
        Asset("ETH", "Ethereum", 3852.93, 5),
        Asset("SOL", "Solana", 184.62, 4),
        Asset("AVAX", "Avalanche", 37.50, 3),
        Asset("BNB", "BNB", 651.11, 4),
        Asset("USDT", "Tether", 1.0, 2),
        Asset("USDC", "USD Coin", 0.996, 2),
    )
}
CRYPTO_ORDER = ["SOL", "AVAX", "ETH", "BNB", "USDT"]

# (nº de barras, dias por barra, variação alvo do período)
RANGES: dict[str, tuple[int, int, float]] = {
    "1S": (7, 1, 0.02),
    "1M": (30, 1, 0.14),
    "6M": (26, 7, 0.40),
    "1A": (52, 7, 0.85),
    "Tudo": (48, 30, 2.40),
}


@dataclass(frozen=True)
class Quote:
    send: str
    receive: str
    amount: float
    value_usd: float
    service_fee_usd: float
    gas_fee_usd: float
    receive_amount: float
    rate: float  # quantas unidades de `send` valem 1 `receive`


@dataclass(frozen=True)
class Decision:
    """Uma tomada de decisão de um agente (ou do usuário, no caso de swap manual)."""

    kind: str  # 'buy' | 'sell' | 'hold' | 'rebalance' | 'swap'
    title: str
    detail: str  # justificativa
    amount_text: str  # efeito, ex.: "+ 0,50000 ETH" (vazio se não houve movimento)
    moment: datetime
    agent: str | None = None  # id do agente; preenchido no agregado "Geral"


# (tipo, título, justificativa, efeito)
DECISION_POOL: list[tuple[str, str, str, str]] = [
    ("buy", "Comprou ETH", "Preço 6% abaixo da média de 30 dias", "+ 0,50000 ETH"),
    ("buy", "Comprou SOL", "Rompimento de resistência com volume alto", "+ 3,0000 SOL"),
    ("buy", "Comprou USDC", "Aumentou a reserva em dólar", "+ 500,00 USDC"),
    ("sell", "Vendeu AVAX", "Realização de lucro após alta de 12%", "- 4,000 AVAX"),
    ("sell", "Vendeu BNB", "Reduziu exposição por volatilidade", "- 0,2000 BNB"),
    ("sell", "Vendeu SOL", "Stop acionado em −5%", "- 2,0000 SOL"),
    ("hold", "Manteve ETH", "Sem sinal claro; aguardando próxima janela", ""),
    ("hold", "Manteve USDT", "Reserva de caixa dentro da meta", ""),
    ("rebalance", "Rebalanceou a carteira", "ETH passou de 80% do total", ""),
    ("rebalance", "Ajustou a alocação", "Voltou à meta de risco definida", ""),
]


def demo_decisions(seed: str, now: datetime) -> list[Decision]:
    rng = random.Random(f"ubento-{seed}-decisions")
    picks = rng.sample(DECISION_POOL, 8)
    out, when = [], now - timedelta(minutes=rng.randint(20, 150))
    for kind, title, detail, amount in picks:
        out.append(Decision(kind, title, detail, amount, when))
        when -= timedelta(hours=rng.randint(5, 30), minutes=rng.randint(0, 59))
    return out


def make_quote(send: str, receive: str, amount: float) -> Quote:
    ps, pr = ASSETS[send].price, ASSETS[receive].price
    rate = pr / ps
    if amount <= 0 or send == receive:
        return Quote(send, receive, max(amount, 0.0), 0.0, 0.0, 0.0, 0.0, rate)
    value = amount * ps
    service = value * SERVICE_FEE_RATE
    net = max(0.0, value - service - GAS_FEE_USD)
    return Quote(send, receive, amount, value, service, GAS_FEE_USD, net / pr, rate)


class Store(QObject):
    changed = Signal()

    def __init__(self, now: datetime | None = None, seed: str = "main", scale: float = 1.0) -> None:
        super().__init__()
        self.now = now or datetime.now()
        self.seed = seed
        self.scale = scale
        self.readonly = False  # o agregado "Geral" é só leitura
        self._parts: list[Store] = []
        self.owner_id: str | None = None
        self._load_demo()

    def _load_demo(self) -> None:
        scale = self.scale
        base = {"USD": 6900.00, "ETH": 2.9934, "SOL": 6.5, "AVAX": 14.0, "BNB": 0.45, "USDT": 881.0, "USDC": 364.12}
        self.holdings: dict[str, float] = {k: round(v * scale, 8) for k, v in base.items()}
        self.spent = 1144.0 * scale
        self.income = 3226.0 * scale
        self.crypto_change = 1.7
        self.activity = self._make_activity()
        self.decisions: list[Decision] = demo_decisions(self.seed, self.now)

    def reset(self) -> None:
        """Volta aos dados de demonstração originais (as telas se atualizam via `changed`)."""
        self._load_demo()
        self.changed.emit()

    # -- agregação (aba "Geral") ---------------------------------------------

    @classmethod
    def combined(cls, parts: list[Store], now: datetime | None = None) -> Store:
        store = cls(now=now, seed="geral")
        store.readonly = True
        store.set_parts(parts)
        return store

    def set_parts(self, parts: list[Store]) -> None:
        for old in self._parts:
            old.changed.disconnect(self._sync)
        self._parts = list(parts)
        for part in self._parts:
            part.changed.connect(self._sync)
        self._sync()

    def _sync(self) -> None:
        parts = self._parts
        self.holdings = {sym: round(sum(p.holdings.get(sym, 0.0) for p in parts), 8) for sym in ASSETS}
        self.spent = sum(p.spent for p in parts)
        self.income = sum(p.income for p in parts)
        self.crypto_change = sum(p.crypto_change for p in parts) / len(parts) if parts else 0.0
        self.activity = {}
        for p in parts:
            for day, count in p.activity.items():
                self.activity[day] = self.activity.get(day, 0) + count
        self.decisions = sorted(
            (replace(d, agent=p.owner_id) for p in parts for d in p.decisions), key=lambda d: d.moment, reverse=True
        )
        self.changed.emit()

    # -- patrimônio --------------------------------------------------------

    def value_usd(self, symbol: str) -> float:
        return self.holdings.get(symbol, 0.0) * ASSETS[symbol].price

    def total_usd(self) -> float:
        return sum(self.value_usd(s) for s in self.holdings)

    def crypto_breakdown(self) -> list[tuple[str, float]]:
        return [(s, self.value_usd(s)) for s in CRYPTO_ORDER]

    def crypto_total(self) -> float:
        return sum(v for _, v in self.crypto_breakdown())

    def history(self, range_key: str) -> list[tuple[date, float]]:
        """Série sintética (determinística) que termina no saldo total atual."""
        count, step, target = RANGES[range_key]
        drift = math.log(1 + target) / (count - 1)
        sigma = 1.1 * drift + 0.003
        rng = random.Random(f"ubento-{self.seed}-{range_key}")
        values = [self.total_usd()]
        for _ in range(count - 1):
            r = max(-0.4, rng.gauss(drift, sigma))
            values.append(values[-1] / (1 + r))
        values.reverse()
        today = self.now.date()
        return [(today - timedelta(days=step * (count - 1 - i)), v) for i, v in enumerate(values)]

    def usdc_series(self) -> list[float]:
        rng = random.Random(f"ubento-{self.seed}-usdc")
        n = 44
        raw = [rng.gauss(0, 0.0012) for _ in range(n)]
        for i in range(1, n):  # passeio com leve reversão
            raw[i] = raw[i - 1] * 0.7 + raw[i]
        first, last = 0.9963, ASSETS["USDC"].price
        lo, hi = raw[0], raw[-1]
        return [first + (last - first) * i / (n - 1) + (r - (lo + (hi - lo) * i / (n - 1))) * 0.6 for i, r in enumerate(raw)]

    # -- atividade do mês ---------------------------------------------------

    def _make_activity(self) -> dict[date, int]:
        today = self.now.date()
        rng = random.Random(f"ubento-{self.seed}-{today.year}-{today.month}")
        return {date(today.year, today.month, d): rng.choice([0, 0, 1, 2, 3, 4, 6, 8]) for d in range(1, today.day + 1)}

    def decisions_count(self) -> int:
        return sum(self.activity.values())

    def month_weeks(self) -> list[list[tuple[date | None, int | None]]]:
        """Semanas (seg→dom) do mês corrente; dias futuros vêm com contagem None."""
        today = self.now.date()
        weeks = []
        for week in calendar.Calendar(0).monthdatescalendar(today.year, today.month):
            weeks.append([
                (d, self.activity.get(d)) if d.month == today.month else (None, None)
                for d in week
            ])
        return weeks

    # -- troca -------------------------------------------------------------

    def quote(self, send: str, receive: str, amount: float) -> Quote:
        return make_quote(send, receive, amount)

    def validate(self, send: str, receive: str, amount: float) -> str | None:
        """Devolve o motivo de a troca não poder acontecer, ou None se está ok."""
        if self.readonly:
            return "Escolha um agente para fazer swap"
        if send == receive:
            return "Escolha moedas diferentes"
        if amount <= 0:
            return "Informe um valor"
        if amount > self.holdings.get(send, 0.0) + 1e-9:
            return "Saldo insuficiente"
        if self.quote(send, receive, amount).receive_amount <= 0:
            return "Valor menor que as taxas"
        return None

    def execute(self, send: str, receive: str, amount: float) -> str | None:
        """Executa a troca. Devolve mensagem de erro, ou None em caso de sucesso."""
        problem = self.validate(send, receive, amount)
        if problem:
            return problem
        q = self.quote(send, receive, amount)
        self.holdings[send] = round(self.holdings[send] - amount, 8)
        self.holdings[receive] = round(self.holdings.get(receive, 0.0) + q.receive_amount, 8)
        decimals = ASSETS[receive].decimals
        effect = f"+ {q.receive_amount:,.{decimals}f} {receive}".replace(",", "X").replace(".", ",").replace("X", ".")
        self.decisions.insert(0, Decision("swap", f"Swap {send} → {receive}", "Executado manualmente por você", effect, datetime.now()))
        today = datetime.now().date()
        self.activity[today] = self.activity.get(today, 0) + 1
        self.changed.emit()
        return None
