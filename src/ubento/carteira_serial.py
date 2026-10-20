"""Estado de uma carteira ↔ dados que o SQLite guarda (ADR-001, passo 4).

Fronteira explícita entre os dois mundos: dentro do app a carteira é `float` e hora local ingênua; no banco os valores são **texto decimal**
(o `repr` do float, que volta idêntico, bit a bit) e os instantes são **UTC com `Z`**. A leitura valida tudo ANTES de tocar na carteira:
um estado ilegível levanta `ErroDeEstado` e a carteira fica como estava.
"""

from __future__ import annotations

import math
from datetime import date, datetime, timezone

from .mercado import ATIVOS
from .store import Decision, Store, Trade

VERSAO = 1
STATUS = {"executed", "proposed", "approved", "rejected", "suggested"}
LADOS = {"buy", "sell"}
FORMATO_UTC = "%Y-%m-%dT%H:%M:%SZ"


class ErroDeEstado(Exception):
    """O estado guardado não pôde ser lido. `str(erro)` diz o que está errado."""


# -- valores e instantes -------------------------------------------------------------------------------------------------------------------


def texto(x: float) -> str:
    return repr(float(x))


def numero(valor, campo: str, *, minimo: float | None = None) -> float:
    try:
        x = float(valor)
    except (TypeError, ValueError) as erro:
        raise ErroDeEstado(f"{campo}: “{valor}” não é um número") from erro
    if not math.isfinite(x):
        raise ErroDeEstado(f"{campo}: valor não finito")
    if minimo is not None and x < minimo:
        raise ErroDeEstado(f"{campo}: {x} é menor que o mínimo {minimo}")
    return x


def para_utc(momento: datetime) -> str:
    return momento.astimezone(timezone.utc).strftime(FORMATO_UTC)  # ingênuo = hora local do computador


def de_utc(valor, campo: str) -> datetime:
    try:
        return datetime.strptime(valor, FORMATO_UTC).replace(tzinfo=timezone.utc).astimezone().replace(tzinfo=None)
    except (TypeError, ValueError) as erro:
        raise ErroDeEstado(f"{campo}: “{valor}” não é um instante UTC (AAAA-MM-DDTHH:MM:SSZ)") from erro


# -- decisões ------------------------------------------------------------------------------------------------------------------------------


def _opcional(x: float | None) -> str | None:
    return None if x is None else texto(x)


def _decisao_para_dados(d: Decision) -> dict:
    t = d.trade
    return {
        "uid": d.uid, "kind": d.kind, "title": d.title, "detail": d.detail, "amount_text": d.amount_text, "momento": para_utc(d.moment), "status": d.status,
        "trade": None if t is None else {"side": t.side, "symbol": t.symbol, "qty": texto(t.qty), "usd": texto(t.usd), "fee": texto(t.fee), "preco": texto(t.preco)},
        "value_usd": _opcional(d.value_usd), "fee_usd": texto(d.fee_usd), "pnl_usd": _opcional(d.pnl_usd), "pnl_realizado": bool(d.pnl_realizado),
    }


def _decisao_de_dados(d: dict, i: int) -> Decision:
    campo = f"decisão {i + 1}"
    try:
        if d["status"] not in STATUS:
            raise ErroDeEstado(f"{campo}: status “{d['status']}” desconhecido")
        t = d["trade"]
        trade = None
        if t is not None:
            if t["side"] not in LADOS:
                raise ErroDeEstado(f"{campo}: lado “{t['side']}” desconhecido")
            if t["symbol"] not in ATIVOS:
                raise ErroDeEstado(f"{campo}: ativo “{t['symbol']}” desconhecido")
            trade = Trade(t["side"], t["symbol"], numero(t["qty"], f"{campo}.qty", minimo=0), numero(t["usd"], f"{campo}.usd", minimo=0),
                          numero(t["fee"], f"{campo}.fee", minimo=0), numero(t["preco"], f"{campo}.preco", minimo=0))
        pnl = d["pnl_usd"]
        valor = d["value_usd"]
        return Decision(
            d["kind"], d["title"], d["detail"], d["amount_text"], de_utc(d["momento"], f"{campo}.momento"), status=d["status"], trade=trade, uid=d["uid"],
            value_usd=None if valor is None else numero(valor, f"{campo}.value_usd"), fee_usd=numero(d["fee_usd"], f"{campo}.fee_usd", minimo=0),
            pnl_usd=None if pnl is None else numero(pnl, f"{campo}.pnl_usd"), pnl_realizado=bool(d["pnl_realizado"]),
        )
    except (KeyError, TypeError) as erro:
        raise ErroDeEstado(f"{campo}: campo ausente ou de tipo errado ({erro})") from erro


# -- carteira ------------------------------------------------------------------------------------------------------------------------------


def estado_da_carteira(store: Store) -> dict:
    """Tudo o que muda a carteira, menos o histórico de patrimônio (que vai à parte, ponto a ponto)."""
    return {
        "versao": VERSAO,
        "holdings": {s: texto(q) for s, q in sorted(store.holdings.items())},
        "cost_basis": {s: texto(v) for s, v in sorted(store.cost_basis.items())},
        "activity": {dia.isoformat(): n for dia, n in sorted(store.activity.items())},
        "decisions": [_decisao_para_dados(d) for d in store.decisions],
    }


def pontos_da_carteira(store: Store) -> list[tuple[str, str]]:
    return [(para_utc(quando), texto(valor)) for quando, valor in store.pontos]


def aplicar_estado(store: Store, dados: dict, pontos: list[tuple[str, str]]) -> None:
    """Coloca o estado guardado na carteira. Valida tudo primeiro: ou aplica por inteiro, ou levanta `ErroDeEstado` sem alterar nada."""
    if not isinstance(dados, dict) or dados.get("versao") != VERSAO:
        raise ErroDeEstado(f"versão de estado não suportada: {dados.get('versao') if isinstance(dados, dict) else dados!r}")
    try:
        holdings = {s: numero(q, f"holdings.{s}", minimo=0) for s, q in dados["holdings"].items() if s in ATIVOS}
        cost_basis = {s: numero(v, f"cost_basis.{s}", minimo=0) for s, v in dados["cost_basis"].items() if s in ATIVOS}
        activity: dict[date, int] = {}
        for dia, n in dados["activity"].items():
            try:
                activity[date.fromisoformat(dia)] = int(n)
            except (TypeError, ValueError) as erro:
                raise ErroDeEstado(f"activity: “{dia}” não é uma data") from erro
        decisions = [_decisao_de_dados(d, i) for i, d in enumerate(dados["decisions"])]
    except (KeyError, AttributeError, TypeError) as erro:
        raise ErroDeEstado(f"estado incompleto ou de tipo errado ({erro})") from erro
    curva = [(de_utc(quando, "ponto.instante"), numero(valor, "ponto.valor")) for quando, valor in pontos]
    store.holdings = {**{s: 0.0 for s in ATIVOS}, **holdings}
    store.cost_basis, store.activity, store.decisions = cost_basis, activity, decisions
    if curva:
        store.pontos = curva
