"""Motor de decisão dos agentes.

Funções puras: recebem a configuração e o estado do `Store` e devolvem as decisões
que o algoritmo tomaria hoje. Não alteram nada; quem aplica é o Workspace, de acordo
com o modo (automático, pedir aprovação, só sugerir).

Os sinais de mercado são simulados (determinísticos por ativo e dia), exceto no modo mercado real: ali o sinal é a variação real de 7 dias da Binance.
"""

from __future__ import annotations

import random
from datetime import date, datetime

from .agent_config import AgentConfig
from .formatting import number, pct
from .store import ASSETS, CRYPTO_ORDER, MERCADO, TRADE_FEE_RATE, Decision, Store, Trade

MIN_TRADE_USD = 10.0


def momentum(symbol: str, day: date) -> float:
    """Variação do ativo nos últimos 7 dias, em %: a real da Binance no modo mercado real; no demonstrativo, uma simulada e limitada."""
    if MERCADO.ativo:
        return MERCADO.variacao_7d.get(symbol, 0.0)
    rng = random.Random(f"ubento-mom-{symbol}-{day.isoformat()}")
    return max(-15.0, min(20.0, rng.gauss(2.5, 8.0)))


def _trade(side: str, symbol: str, usd: float) -> Trade:
    """Compra: `usd` é o caixa que sai; a taxa sai do que se recebe (unidades líquidas). Venda: `usd` é qty × preço; a taxa sai do que entra."""
    asset = ASSETS[symbol]
    if side == "buy":
        taxa = round(usd * TRADE_FEE_RATE, 2)
        qty = round((usd - taxa) / asset.price, asset.decimals)
        return Trade(side, symbol, qty, round(usd, 2), taxa)
    qty = round(usd / asset.price, asset.decimals)
    valor = round(qty * asset.price, 2)
    return Trade(side, symbol, qty, valor, round(valor * TRADE_FEE_RATE, 2))


def _effect(trade: Trade) -> str:
    sign = "+" if trade.side == "buy" else "-"
    return f"{sign} {number(trade.qty, ASSETS[trade.symbol].decimals)} {trade.symbol}"


def _buy(symbol: str, usd: float, detail: str, now: datetime, kind: str = "buy", title: str | None = None) -> Decision:
    t = _trade("buy", symbol, usd)
    return Decision(kind, title or f"Comprou {symbol}", detail, _effect(t), now, trade=t, value_usd=t.usd, fee_usd=t.fee, pnl_realizado=False)


def _sell(symbol: str, usd: float, detail: str, now: datetime, kind: str = "sell", title: str | None = None) -> Decision:
    t = _trade("sell", symbol, usd)
    return Decision(kind, title or f"Vendeu {symbol}", detail, _effect(t), now, trade=t, value_usd=t.usd, fee_usd=t.fee)


def _hold(title: str, detail: str, now: datetime) -> Decision:
    return Decision("hold", title, detail, "", now)


def _cash(cfg: AgentConfig, store: Store) -> tuple[float, float]:
    """(patrimônio total, caixa gastável acima da reserva)."""
    total = store.total_usd()
    reserve = total * cfg.reserve_pct / 100
    return total, max(0.0, store.holdings.get("USD", 0.0) - reserve)


def _largest(store: Store, assets: list[str]) -> str:
    return max(assets, key=store.value_usd)


# -- algoritmos ----------------------------------------------------------------


def _momentum(cfg: AgentConfig, store: Store, now: datetime) -> list[Decision]:
    total, spendable = _cash(cfg, store)
    buy_threshold = 9.0 - 1.2 * cfg.risk
    size_factor = 0.6 + 0.2 * cfg.risk
    signals = {a: momentum(a, now.date()) for a in cfg.assets}
    out: list[Decision] = []
    for sym in sorted(signals, key=signals.get, reverse=True):
        m, held = signals[sym], store.value_usd(sym)
        if held > MIN_TRADE_USD and m <= -cfg.stop_loss_pct:
            out.append(_sell(sym, held, f"Stop acionado: queda de {pct(m)} em 7 dias", now))
        elif held > MIN_TRADE_USD and m >= cfg.take_profit_pct:
            out.append(_sell(sym, held * 0.3, f"Realizou lucro após alta de {pct(m)} em 7 dias", now))
        elif m >= buy_threshold and spendable > MIN_TRADE_USD:
            room = total * cfg.max_position_pct / 100 - held
            amount = min(spendable * cfg.trade_size_pct / 100 * size_factor, room)
            if amount > MIN_TRADE_USD:
                spendable -= amount
                out.append(_buy(sym, amount, f"Tendência de alta: +{pct(m)} em 7 dias", now))
    return out or [_hold(f"Manteve {_largest(store, cfg.assets)}", "Sinais fracos: nenhum ativo passou do limite de tendência", now)]


def _rebalance(cfg: AgentConfig, store: Store, now: datetime) -> list[Decision]:
    values = {a: store.value_usd(a) for a in cfg.assets}
    pool = sum(values.values())
    if pool <= 0 or len(values) < 2:
        return [_hold("Manteve a carteira", "Sem posição suficiente para rebalancear", now)]
    target = pool / len(values)
    _, spendable = _cash(cfg, store)
    out: list[Decision] = []
    for sym in sorted(values, key=lambda a: abs(values[a] - target), reverse=True)[:3]:
        deviation = (values[sym] - target) / pool * 100
        if abs(deviation) <= cfg.rebalance_threshold_pct:
            continue
        if deviation > 0:
            out.append(_sell(sym, values[sym] - target, f"{sym} estava {pct(deviation)} acima da meta", now, "rebalance", f"Rebalanceou {sym}"))
        else:
            amount = min(target - values[sym], spendable)
            if amount > MIN_TRADE_USD:
                spendable -= amount
                out.append(_buy(sym, amount, f"{sym} estava {pct(deviation)} abaixo da meta", now, "rebalance", f"Rebalanceou {sym}"))
    return out or [_hold("Carteira dentro da meta", f"Nenhum ativo desviou mais de {cfg.rebalance_threshold_pct}%", now)]


def _dca(cfg: AgentConfig, store: Store, now: datetime) -> list[Decision]:
    _, spendable = _cash(cfg, store)
    sym = cfg.assets[now.date().toordinal() % len(cfg.assets)]
    amount = spendable * cfg.trade_size_pct / 100
    if amount > MIN_TRADE_USD:
        return [_buy(sym, amount, f"Compra recorrente de {cfg.trade_size_pct}% do caixa disponível", now)]
    return [_hold("Compra recorrente adiada", "Sem caixa disponível acima da reserva", now)]


def _conservative(cfg: AgentConfig, store: Store, now: datetime) -> list[Decision]:
    total = store.total_usd()
    if total <= 0:
        return []
    limit = 30 + 10 * cfg.risk
    share = store.crypto_total() / total * 100
    if share > limit:
        sym = _largest(store, [a for a in CRYPTO_ORDER if a != "USDT"])
        excess = (share - limit) / 100 * total
        return [_sell(sym, min(excess, store.value_usd(sym)), f"Cripto em {pct(share)} do patrimônio; limite de {limit}%", now, title=f"Reduziu {sym}")]
    return [_hold("Manteve a exposição", f"Cripto em {pct(share)} do patrimônio, abaixo do limite de {limit}%", now)]


STRATEGY_FUNCS = {"momentum": _momentum, "rebalance": _rebalance, "dca": _dca, "conservative": _conservative}


def decide(cfg: AgentConfig, store: Store, now: datetime | None = None) -> list[Decision]:
    """Decisões que o algoritmo do agente tomaria agora (sem aplicá-las)."""
    if not cfg.active or cfg.strategy == "manual":
        return []
    return STRATEGY_FUNCS[cfg.strategy](cfg, store, now or datetime.now())
