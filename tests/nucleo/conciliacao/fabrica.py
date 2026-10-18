"""Construtores de dados de teste (fictícios) para a conciliação."""

from datetime import UTC, datetime, timedelta
from decimal import Decimal

from ubento.nucleo.conciliacao import PoliticaConciliacao, RegistroExterno, conciliar
from ubento.nucleo.esquema import Execucao

META = "meta-tokx-001"
FONTE = "corretora-sim"
BASE = datetime(2026, 10, 20, 10, 0, 0, tzinfo=UTC)
AGORA = BASE + timedelta(hours=2)
POLITICA = PoliticaConciliacao(janela_atraso_segundos=3600, tolerancia_horario_segundos=60, janela_candidatos_segundos=300)


def d(valor) -> Decimal:
    return Decimal(str(valor))


def execucao(id_="ex-1", *, meta=META, bruta="10", taxa="0.05", preco="9.5", lado="compra", refs=("fill-001",), minutos=0, **extra) -> Execucao:
    referencias = [r if isinstance(r, dict) else {"fonte_id": FONTE, "id_externo": r} for r in refs]
    dados = dict(
        id=id_, meta_id=meta, ativo_id="tokx", lado=lado, quantidade_bruta=bruta, taxa_no_ativo=taxa,
        quantidade_liquida=str(d(bruta) - d(taxa)), preco_executado=preco, executada_em=BASE + timedelta(minutes=minutos),
        confirmada_em=BASE + timedelta(minutes=minutos + 1), fonte_id="registro-manual", origem="simulado", referencias_externas=referencias,
    )
    if lado == "estorno_compra":
        dados.setdefault("estorna_execucao_id", "ex-1")
    dados.update(extra)
    return Execucao(**dados)


def externo(id_="fill-001", *, qtd="10", preco="9.5", taxas=(("tokx", "0.05"),), versao=1, status="confirmado", lado="compra",
            minutos=0, recebido_min=0, estorna=None, **extra) -> RegistroExterno:
    dados = dict(
        fonte_id=FONTE, id_externo=id_, versao=versao, mercado_id="bolsa-a", ativo_id="tokx", moeda_cotacao_id="usd", lado=lado,
        quantidade=qtd, preco=preco, taxas=[{"ativo_id": a, "valor": v} for a, v in taxas], status=status,
        executado_em=BASE + timedelta(minutes=minutos), recebido_em=BASE + timedelta(minutes=minutos, seconds=30 + recebido_min * 60),
        origem="simulado", estorna_id_externo=estorna,
    )
    dados.update(extra)
    return RegistroExterno(**dados)


def rodar(execucoes, externos, *, politica=POLITICA, agora=AGORA, **kw):
    return conciliar(execucoes, externos, politica=politica, agora=agora, **kw)


def status(relatorio, id_):
    return next(r for r in relatorio.execucoes if r.execucao_id == id_)


def comprovado(relatorio, meta=META):
    return next(p for p in relatorio.progresso if p.meta_id == meta).comprovado
