"""Ponte carteira → núcleo (ADR-001, passo 1).

Quando um agente EXECUTA uma compra, a ponte a registra como execução das metas daquele agente que miram o mesmo ativo. A conversão é explícita:
`float` e hora local da carteira viram `Decimal` e UTC com fuso, que é o que o núcleo exige.

O que a ponte nunca faz:
- registrar uma decisão que ainda não foi executada (aprovar não executa);
- registrar em meta REAL (`cenario=False`): a execução da carteira é simulada, e só combina com evidência simulada;
- registrar **vendas**: o núcleo mede aquisição e só tem os lados compra e estorno de compra;
- comprovar nada: a execução nasce SIMULADA e SEM registro externo, então fica pendente até haver evidência correspondente;
- quebrar a carteira: qualquer falha vira um aviso, e a compra já aconteceu.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from decimal import Decimal

from PySide6.QtCore import QObject, Signal
from pydantic import ValidationError

from .metas import ErroDeRegistro, ServicoMetas
from .nucleo.avaliacao.estado import TERMINAIS
from .nucleo.esquema import Execucao, LadoExecucao, Meta, OrigemDado
from .mercado import ATIVOS
from .store import Decision
from .workspace import Workspace

log = logging.getLogger(__name__)

FONTE_CARTEIRA = "ubento-carteira"
MOEDAS_DOLAR = frozenset({"usd", "usdt"})  # USDT é a referência do dólar na carteira (US$ 1,00)


class NaoAplicavel(Exception):
    """A decisão não deve virar execução desta meta. `str(erro)` é o motivo."""


def _decimal(valor: float, casas: int) -> Decimal:
    return Decimal(f"{valor:.{casas}f}")  # sempre a partir de texto, nunca do float cru


def execucao_da_decisao(decisao: Decision, meta: Meta, ativada_em: datetime) -> Execucao:
    """Converte uma compra executada na `Execucao` do núcleo, ou levanta `NaoAplicavel` com o motivo."""
    if decisao.status != "executed":
        raise NaoAplicavel("a decisão ainda não foi executada")
    t = decisao.trade
    if t is None:
        raise NaoAplicavel("a decisão não tem movimento de dinheiro")
    if t.side != "buy":
        raise NaoAplicavel("venda não entra: o núcleo mede aquisição e não tem lado de venda")
    ativo = t.symbol.lower()
    if ativo != meta.objetivo.ativo_id:
        raise NaoAplicavel(f"o ativo ({ativo}) não é o ativo da meta ({meta.objetivo.ativo_id})")
    moeda = meta.objetivo.moeda_cotacao_id
    if moeda not in MOEDAS_DOLAR:
        raise NaoAplicavel(f"a moeda de cotação da meta ({moeda}) não é dólar")
    quando = decisao.moment.astimezone(timezone.utc)  # a carteira guarda hora local ingênua
    if quando < ativada_em:
        raise NaoAplicavel("a compra foi feita antes da ativação da meta")
    if quando > meta.objetivo.prazo:
        raise NaoAplicavel("a compra foi feita depois do prazo da meta")

    preco = t.preco or (t.usd - t.fee) / t.qty  # trades antigos não guardavam o preço: o valor líquido por unidade é o que sobra
    casas = ATIVOS[t.symbol].decimals
    liquida = _decimal(t.qty, casas)  # o que a carteira recebeu
    taxa = _decimal(t.fee / preco, casas)  # a taxa sai do que se recebe: é cobrada no próprio ativo
    try:
        return Execucao(
            id=f"dec-{decisao.uid}", meta_id=meta.id, ativo_id=ativo, lado=LadoExecucao.COMPRA,
            quantidade_bruta=liquida + taxa, taxa_no_ativo=taxa, quantidade_liquida=liquida,
            preco_executado=_decimal(preco, 8), moeda_cotacao_id=moeda,
            executada_em=quando, confirmada_em=quando, fonte_id=FONTE_CARTEIRA, origem=OrigemDado.SIMULADO,
        )
    except ValidationError as erro:
        raise NaoAplicavel(f"a execução não passou na validação do núcleo: {erro.errors()[0]['msg']}") from erro


class PonteCarteiraMetas(QObject):
    registrada = Signal(str, str)  # (meta, execução): uma compra entrou numa meta
    falhou = Signal(str)

    def __init__(self, workspace: Workspace, servico: ServicoMetas):
        super().__init__()
        self._servico = servico
        workspace.decisao_executada.connect(self.ao_executar)

    def ao_executar(self, agente_id: str, decisao: Decision) -> None:
        try:
            metas = self._servico.metas(agente_id)
        except Exception as erro:  # noqa: BLE001 - a carteira nunca pode quebrar por causa da ponte
            log.exception("ponte carteira→metas: não foi possível listar as metas")
            self.falhou.emit(f"Não foi possível registrar a compra nas metas: {erro}")
            return
        for meta_id in metas:
            try:
                self._enviar(meta_id, decisao)
            except Exception as erro:  # noqa: BLE001
                log.exception("ponte carteira→metas: falha ao registrar em %s", meta_id)
                self.falhou.emit(f"Não foi possível registrar a compra na meta {meta_id}: {erro}")

    def _enviar(self, meta_id: str, decisao: Decision) -> None:
        if not self._servico.repo.meta_e_cenario(meta_id):
            return  # meta REAL só aceita execução observada; esta nasce simulada e só prova (ou diverge) contra evidência simulada
        meta, ativacao = self._servico.repo.carregar_meta(meta_id)
        ultima = self._servico.repo.ultima_avaliacao(meta_id)
        if ultima is not None and ultima[0].estado in TERMINAIS:
            return  # meta encerrada (atingida, expirada, invalidada ou cancelada)
        try:
            execucao = execucao_da_decisao(decisao, meta, ativacao.ativada_em)
        except NaoAplicavel as motivo:
            log.debug("ponte carteira→metas: %s não entra em %s (%s)", decisao.uid, meta_id, motivo)
            return
        try:
            nova = self._servico.registrar_execucao(meta_id, execucao)
        except ErroDeRegistro as erro:
            self.falhou.emit(f"A meta {meta_id} recusou a compra: {erro}")
            return
        if nova:
            self.registrada.emit(meta_id, execucao.id)
