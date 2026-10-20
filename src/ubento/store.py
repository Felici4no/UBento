"""Estado do app em memória, com dados de demonstração.

Por enquanto só interface: nada aqui persiste. A camada SQLite entra depois,
mantendo esta mesma API (`Store`) para as telas.
"""

from __future__ import annotations

import calendar
import math
import random
from dataclasses import dataclass, field, replace
from uuid import uuid4
from datetime import date, datetime, timedelta

from PySide6.QtCore import QObject, Signal

from .mercado import ATIVOS, AGUARDANDO_PRECOS, Mercado

SERVICE_FEE_RATE = 0.023
GAS_FEE_USD = 1.32
TRADE_FEE_RATE = 0.001  # taxa de 0,10% sobre cada compra/venda dos agentes (a mesma da Binance spot)
CAPITAL_INICIAL_REAL = 10_000.0  # caixa (em USD) de cada carteira nova do modo mercado real; as ordens são simuladas, nunca enviadas à corretora


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
class Trade:
    """Movimento concreto de uma decisão: compra ou venda de um ativo contra dólar."""

    side: str  # 'buy' | 'sell'
    symbol: str
    qty: float  # unidades que entram (compra, já líquidas da taxa) ou saem (venda)
    usd: float  # valor negociado: o caixa que sai numa compra; qty × preço numa venda
    fee: float = 0.0  # taxa em USD. Na compra sai do que se recebe; na venda sai do que entra no caixa
    preco: float = 0.0  # preço do ativo em USD no momento da ordem (0 = não registrado: trades antigos)


@dataclass(frozen=True)
class Decision:
    """Uma tomada de decisão de um agente (ou do usuário, no caso de swap manual)."""

    kind: str  # 'buy' | 'sell' | 'hold' | 'rebalance' | 'swap'
    title: str
    detail: str  # justificativa
    amount_text: str  # efeito, ex.: "+ 0,50000 ETH" (vazio se não houve movimento)
    moment: datetime
    agent: str | None = None  # id do agente; preenchido no agregado "Geral"
    status: str = "executed"  # 'executed' | 'proposed' | 'approved' | 'rejected' | 'suggested'
    trade: Trade | None = None
    uid: str = field(default_factory=lambda: uuid4().hex[:10])
    # Livro da decisão (None = sem dinheiro movimentado). `pnl_usd` já é LÍQUIDO da taxa: valor recebido − custo do que foi dado.
    value_usd: float | None = None  # valor movimentado (o que foi aplicado)
    fee_usd: float = 0.0
    pnl_usd: float | None = None  # só existe depois de executada; antes disso a decisão só tem valor e taxa estimados
    pnl_realizado: bool = True  # venda/troca realizam o resultado; compra deixa a posição em aberto


# (tipo, título, justificativa, efeito, ativo, quantidade, resultado da venda como fração do valor vendido, já antes da taxa)
DECISION_POOL: list[tuple[str, str, str, str, str | None, float, float | None]] = [
    ("buy", "Comprou ETH", "Preço 6% abaixo da média de 30 dias", "+ 0,50000 ETH", "ETH", 0.50000, None),
    ("buy", "Comprou SOL", "Rompimento de resistência com volume alto", "+ 3,0000 SOL", "SOL", 3.0000, None),
    ("buy", "Comprou USDC", "Aumentou a reserva em dólar", "+ 500,00 USDC", "USDC", 500.0, None),
    ("sell", "Vendeu AVAX", "Realização de lucro após alta de 12%", "- 4,000 AVAX", "AVAX", 4.000, 0.107),
    ("sell", "Vendeu BNB", "Reduziu exposição por volatilidade", "- 0,2000 BNB", "BNB", 0.2000, 0.012),
    ("sell", "Vendeu SOL", "Stop acionado em −5%", "- 2,0000 SOL", "SOL", 2.0000, -0.05),
    ("hold", "Manteve ETH", "Sem sinal claro; aguardando próxima janela", "", None, 0.0, None),
    ("hold", "Manteve USDT", "Reserva de caixa dentro da meta", "", None, 0.0, None),
    ("rebalance", "Rebalanceou a carteira", "ETH passou de 80% do total", "", None, 0.0, None),
    ("rebalance", "Ajustou a alocação", "Voltou à meta de risco definida", "", None, 0.0, None),
]


def demo_decisions(seed: str, now: datetime, mercado: Mercado) -> list[Decision]:
    rng = random.Random(f"ubento-{seed}-decisions")
    picks = rng.sample(DECISION_POOL, 8)
    out, when = [], now - timedelta(minutes=rng.randint(20, 150))
    for kind, title, detail, amount, symbol, qty, ganho in picks:
        livro: dict = {}
        if symbol:  # o histórico de demonstração também traz valor, taxa e resultado, no mesmo critério das decisões executadas agora
            valor = round(qty * mercado.preco(symbol), 2)
            taxa = round(valor * TRADE_FEE_RATE, 2)
            if kind == "buy":
                livro = dict(value_usd=valor, fee_usd=taxa, pnl_usd=-taxa, pnl_realizado=False)  # em aberto: no ato só se perdeu a taxa
            else:
                livro = dict(value_usd=valor, fee_usd=taxa, pnl_usd=round(valor * (ganho or 0.0) - taxa, 2))
        out.append(Decision(kind, title, detail, amount, when, **livro))
        when -= timedelta(hours=rng.randint(5, 30), minutes=rng.randint(0, 59))
    return out


def make_quote(send: str, receive: str, amount: float, mercado: Mercado | None = None) -> Quote:
    mercado = mercado or Mercado()  # sem mercado informado: preços de demonstração
    ps, pr = mercado.preco(send), mercado.preco(receive)
    rate = pr / ps
    if amount <= 0 or send == receive:
        return Quote(send, receive, max(amount, 0.0), 0.0, 0.0, 0.0, 0.0, rate)
    value = amount * ps
    service = value * SERVICE_FEE_RATE
    net = max(0.0, value - service - GAS_FEE_USD)
    return Quote(send, receive, amount, value, service, GAS_FEE_USD, net / pr, rate)


class Store(QObject):
    changed = Signal()
    executed = Signal(object)  # uma decisão com movimento acabou de ser executada (já com valor, taxa e resultado preenchidos)

    def __init__(self, now: datetime | None = None, seed: str = "main", scale: float = 1.0, real: bool = False, mercado: Mercado | None = None) -> None:
        super().__init__()
        self.mercado = mercado or Mercado()  # preços, sinais, frescor e relógio; o Workspace entrega o mesmo a todas as carteiras
        self.now = now or self.mercado.agora()
        self.seed = seed
        self.scale = scale
        self.real = real  # modo mercado real: carteira nova, preços ao vivo, histórico observado
        self.readonly = False  # o agregado "Geral" é só leitura
        self._parts: list[Store] = []
        self.owner_id: str | None = None
        self.pontos: list[tuple[datetime, float]] = []  # patrimônio observado ao longo do tempo (só no modo real)
        self.usdc_observado: list[float] = []
        self._load()

    def _load(self) -> None:
        self._load_real() if self.real else self._load_demo()

    def _load_real(self) -> None:
        """Carteira nova: só caixa, sem custo de aquisição, sem decisões, sem atividade e sem nenhum número simulado."""
        self.holdings = {s: 0.0 for s in ATIVOS}
        self.holdings["USD"] = CAPITAL_INICIAL_REAL
        self.cost_basis = {}
        self.spent = self.income = 0.0
        self.crypto_change = 0.0
        hoje = self.now.date()
        self.activity = {date(hoje.year, hoje.month, d): 0 for d in range(1, hoje.day + 1)}
        self.decisions = []
        self.pontos = [(self.now, self.total_usd())]
        self.usdc_observado = []

    def definir_modo(self, real: bool) -> None:
        """Troca entre demonstração e mercado real, descartando o estado do modo anterior (as telas se atualizam via `changed`)."""
        self.real = real
        self._load()
        if self._parts:
            self._sync()
            if real:
                self.pontos = [(self.now, self.total_usd())]  # o histórico do Geral recomeça junto com as carteiras
        else:
            self.changed.emit()

    def registrar_ponto(self, agora: datetime) -> None:
        """Anota o patrimônio e o preço do USDC observados agora e recalcula a variação da carteira cripto. Não emite `changed`."""
        total = self.total_usd()
        if self.pontos and (agora - self.pontos[-1][0]).total_seconds() < 60:
            self.pontos[-1] = (agora, total)  # no máximo um ponto por minuto
        else:
            self.pontos.append((agora, total))
        del self.pontos[:-20_000]
        self.usdc_observado = (self.usdc_observado + [self.mercado.preco("USDC")])[-44:]
        pesos = {s: self.value_usd(s) for s in CRYPTO_ORDER if self.value_usd(s) > 0}
        soma = sum(pesos.values())
        self.crypto_change = sum(v * self.mercado.variacao_7d.get(s, 0.0) for s, v in pesos.items()) / soma if soma else 0.0

    def _load_demo(self) -> None:
        scale = self.scale
        base = {"USD": 6900.00, "ETH": 2.9934, "SOL": 6.5, "AVAX": 14.0, "BNB": 0.45, "USDT": 881.0, "USDC": 364.12}
        self.holdings: dict[str, float] = {k: round(v * scale, 8) for k, v in base.items()}
        # custo de aquisição (USD) do que está em carteira: base para o resultado realizado das vendas. Demonstração: o preço de entrada
        # de cada ativo é 22% abaixo a 18% acima do preço atual, de forma determinística por agente.
        self.cost_basis: dict[str, float] = {
            s: round(q * self.mercado.preco(s) * random.Random(f"ubento-basis-{self.seed}-{s}").uniform(0.82, 1.18), 8) for s, q in self.holdings.items() if s != "USD"
        }
        self.spent = 1144.0 * scale
        self.income = 3226.0 * scale
        self.crypto_change = 1.7
        self.activity = self._make_activity()
        self.decisions: list[Decision] = demo_decisions(self.seed, self.now, self.mercado)

    def reset(self) -> None:
        """Volta ao estado inicial do modo atual (as telas se atualizam via `changed`)."""
        self._load()
        self.changed.emit()

    # -- agregação (aba "Geral") ---------------------------------------------

    @classmethod
    def combined(cls, parts: list[Store], now: datetime | None = None, real: bool = False, mercado: Mercado | None = None) -> Store:
        store = cls(now=now, seed="geral", real=real, mercado=mercado)
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
        self.holdings = {sym: round(sum(p.holdings.get(sym, 0.0) for p in parts), 8) for sym in ATIVOS}
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
        return self.holdings.get(symbol, 0.0) * self.mercado.preco(symbol)

    def total_usd(self) -> float:
        return sum(self.value_usd(s) for s in self.holdings)

    def crypto_breakdown(self) -> list[tuple[str, float]]:
        return [(s, self.value_usd(s)) for s in CRYPTO_ORDER]

    def crypto_total(self) -> float:
        return sum(v for _, v in self.crypto_breakdown())

    def history(self, range_key: str) -> list[tuple[date, float]]:
        """Série sintética (determinística) que termina no saldo total atual. No modo real, a série OBSERVADA do patrimônio."""
        count, step, target = RANGES[range_key]
        if self.real:
            return self._historico_observado(count, step)
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

    def _historico_observado(self, count: int, step: int) -> list[tuple[date, float]]:
        """`count` pontos, um a cada `step` dias, terminando hoje. Cada um é o último patrimônio OBSERVADO até aquele dia; antes de a carteira existir
        a linha é o primeiro valor visto (o capital inicial), nunca um número inventado."""
        hoje = self.pontos[-1][0].date()
        ordenados = sorted(self.pontos, key=lambda ponto: ponto[0])
        out: list[tuple[date, float]] = []
        for i in range(count):
            dia = hoje - timedelta(days=step * (count - 1 - i))
            valor = ordenados[0][1]
            for quando, v in ordenados:
                if quando.date() > dia:
                    break
                valor = v
            out.append((dia, valor))
        return out

    def usdc_series(self) -> list[float]:
        if self.real:
            obs = self.usdc_observado or [self.mercado.preco("USDC")]
            return obs if len(obs) > 1 else obs * 2
        rng = random.Random(f"ubento-{self.seed}-usdc")
        n = 44
        raw = [rng.gauss(0, 0.0012) for _ in range(n)]
        for i in range(1, n):  # passeio com leve reversão
            raw[i] = raw[i - 1] * 0.7 + raw[i]
        first, last = 0.9963, self.mercado.preco("USDC")
        lo, hi = raw[0], raw[-1]
        return [first + (last - first) * i / (n - 1) + (r - (lo + (hi - lo) * i / (n - 1))) * 0.6 for i, r in enumerate(raw)]

    # -- atividade do mês ---------------------------------------------------

    def _make_activity(self) -> dict[date, int]:
        today = self.now.date()
        rng = random.Random(f"ubento-{self.seed}-{today.year}-{today.month}")
        return {date(today.year, today.month, d): rng.choice([0, 0, 1, 2, 3, 4, 6, 8]) for d in range(1, today.day + 1)}

    # -- decisões dos agentes -----------------------------------------------

    def apply_trade(self, trade: Trade) -> bool:
        """Aplica uma compra/venda aos saldos. Falso (sem alterar nada) se faltar saldo."""
        return self.executar_trade(trade) is not None

    def executar_trade(self, trade: Trade) -> float | None:
        """Aplica a compra/venda e devolve o RESULTADO em USD, líquido da taxa (valor recebido − custo do que foi dado).
        Compra: sai `usd` do caixa e entram unidades já líquidas da taxa, então o resultado no ato é −taxa (posição em aberto).
        Venda: entra `usd − taxa` no caixa e o custo das unidades vendidas sai do custo médio. None (sem alterar nada) se faltar saldo."""
        if trade.side == "buy":
            if self.holdings.get("USD", 0.0) + 1e-9 < trade.usd:
                return None
            self.holdings["USD"] = round(self.holdings["USD"] - trade.usd, 8)
            self.holdings[trade.symbol] = round(self.holdings.get(trade.symbol, 0.0) + trade.qty, 8)
            self.cost_basis[trade.symbol] = round(self.cost_basis.get(trade.symbol, 0.0) + trade.usd, 8)  # o custo inclui a taxa paga
            return -trade.fee  # o custo de entrar é a taxa (as unidades já vêm líquidas dela)
        em_carteira = self.holdings.get(trade.symbol, 0.0)
        if em_carteira + 1e-9 < trade.qty:
            return None
        custo = self.cost_basis.get(trade.symbol, 0.0) * (trade.qty / em_carteira if em_carteira else 0.0)
        self.cost_basis[trade.symbol] = round(self.cost_basis.get(trade.symbol, 0.0) - custo, 8)
        self.holdings[trade.symbol] = round(em_carteira - trade.qty, 8)
        recebido = trade.usd - trade.fee
        self.holdings["USD"] = round(self.holdings.get("USD", 0.0) + recebido, 8)
        return round(recebido - custo, 2)

    @staticmethod
    def _com_livro(d: Decision, pnl: float | None) -> Decision:
        """Preenche valor, taxa e resultado de uma decisão com movimento. Sem movimento (manter, rebalancear sem ordem) fica como está."""
        if d.trade is None:
            return d
        return replace(d, value_usd=d.trade.usd, fee_usd=d.trade.fee, pnl_usd=pnl, pnl_realizado=d.trade.side == "sell")

    def add_decision(self, decision: Decision) -> str | None:
        """Registra uma decisão no topo da lista; executa o movimento se ela já nasce executada."""
        pnl = None
        if decision.status == "executed" and decision.trade:
            pnl = self.executar_trade(decision.trade)
            if pnl is None:
                return "Saldo insuficiente"
        self.decisions.insert(0, self._com_livro(decision, pnl))
        self.changed.emit()
        if decision.status == "executed" and decision.trade:
            self.executed.emit(self.decisions[0])
        return None

    def resolve_decision(self, uid: str, approve: bool) -> str | None:
        """Aprova ou recusa uma proposta. Devolve mensagem de erro, ou None.

        **Aprovar não é executar.** A aprovação só autoriza: não mexe nos saldos nem no progresso de nenhuma meta.
        A execução é um registro separado (`registrar_execucao`), feito quando a operação foi de fato confirmada.
        """
        index = next((i for i, d in enumerate(self.decisions) if d.uid == uid and d.status == "proposed"), None)
        if index is None:
            return "Proposta não encontrada"
        d = self.decisions[index]
        self.decisions[index] = replace(d, status="approved" if approve else "rejected")
        self.changed.emit()
        return None

    def registrar_execucao(self, uid: str, now: datetime | None = None) -> str | None:
        """Registra que uma decisão APROVADA foi executada (confirmada). Só então os saldos mudam."""
        index = next((i for i, d in enumerate(self.decisions) if d.uid == uid), None)
        if index is None or self.decisions[index].status != "approved":
            return "Só uma decisão aprovada pode ter a execução registrada"
        d = self.decisions[index]
        pnl = None
        if d.trade:
            pnl = self.executar_trade(d.trade)
            if pnl is None:
                return "Saldo insuficiente para registrar a execução"
        self.decisions[index] = replace(self._com_livro(d, pnl), status="executed", moment=now or self.mercado.agora())
        self.changed.emit()
        if d.trade:
            self.executed.emit(self.decisions[index])
        return None

    def resultado_do_dia(self, dia: date) -> float:
        """Soma do resultado (líquido de taxa) das decisões EXECUTADAS no dia. Propostas e decisões sem dinheiro não contam;
        posições em aberto só entram pelo que já se pagou de taxa (o resultado de uma compra no ato é −taxa)."""
        return sum(d.pnl_usd for d in self.decisions if d.status == "executed" and d.pnl_usd is not None and d.moment.date() == dia)

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
        return make_quote(send, receive, amount, self.mercado)

    def validate(self, send: str, receive: str, amount: float) -> str | None:
        """Devolve o motivo de a troca não poder acontecer, ou None se está ok."""
        if self.readonly:
            return "Escolha um agente para fazer swap"
        if self.real and not self.mercado.fresco():
            return AGUARDANDO_PRECOS
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
        # troca = baixa do que se deu (pelo custo médio) + entrada do que se recebeu (pelo valor de mercado): o resultado já sai líquido das taxas
        em_carteira = self.holdings[send]
        custo = amount if send == "USD" else self.cost_basis.get(send, 0.0) * (amount / em_carteira if em_carteira else 0.0)
        if send != "USD":
            self.cost_basis[send] = round(self.cost_basis.get(send, 0.0) - custo, 8)
        recebido_usd = q.receive_amount * self.mercado.preco(receive)
        if receive != "USD":
            self.cost_basis[receive] = round(self.cost_basis.get(receive, 0.0) + recebido_usd, 8)
        self.holdings[send] = round(self.holdings[send] - amount, 8)
        self.holdings[receive] = round(self.holdings.get(receive, 0.0) + q.receive_amount, 8)
        decimals = ATIVOS[receive].decimals
        agora = self.mercado.agora()
        effect = f"+ {q.receive_amount:,.{decimals}f} {receive}".replace(",", "X").replace(".", ",").replace("X", ".")
        self.decisions.insert(0, Decision(
            "swap", f"Swap {send} → {receive}", "Executado manualmente por você", effect, agora,
            value_usd=round(q.value_usd, 2), fee_usd=round(q.service_fee_usd + q.gas_fee_usd, 2), pnl_usd=round(recebido_usd - custo, 2), pnl_realizado=True,
        ))
        today = agora.date()
        self.activity[today] = self.activity.get(today, 0) + 1
        self.changed.emit()
        return None
