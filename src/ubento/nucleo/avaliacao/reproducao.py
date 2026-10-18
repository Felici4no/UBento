"""Reprodução ponta a ponta de uma meta: arquivo YAML/JSON com dados SIMULADOS e o resultado esperado por momento.

Cada momento roda o fluxo completo (execuções → conciliação → progresso → avaliação → eventos), acrescenta os
eventos novos à história e ao razão, e reprocessa o mesmo momento para provar que não há duplicação.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Annotated, Literal

from pydantic import Field

from ..canonico import hash_contrato
from ..carregador import carregar_arquivo
from ..conciliacao.conciliador import conciliar
from ..conciliacao.eventos import EventoConciliacao
from ..conciliacao.modelos import (
    Cobertura, CoberturaExecucoes, Movimentacao, PoliticaConciliacao, RegistroExterno, RelatorioConciliacao, SaldoObservado, VinculoManual,
)
from ..esquema import Ativacao, EstadoMeta, Evento, Execucao, Meta, Modelo, Observacao
from ..regras import Snapshot
from ..tipos import Identificador, Instante, Numero, Texto, Tri
from .avaliador import avaliar_meta
from .modelos import MotivoAvaliacao, MotivoEscopo, ResultadoAvaliacao


class EsperadoMeta(Modelo):
    estado: EstadoMeta | None = None
    eventos: tuple[str, ...] | None = None  # tipos dos eventos NOVOS da meta, na ordem
    eventos_conciliacao: tuple[str, ...] | None = None
    quantidade_comprovada: Numero | None = None
    quantidade_preservada: Numero | None = None
    completa: bool | None = None
    elegibilidade: Tri | None = None
    motivos_elegibilidade: tuple[MotivoAvaliacao, ...] = ()  # cada um deve estar presente
    orcamento: Tri | None = None
    bloqueada_por_dados: bool | None = None
    aguardando_evidencia: bool | None = None
    em_carencia: bool | None = None
    orfaos_relevantes: tuple[Identificador, ...] | None = None
    orfaos_ignorados: dict[Identificador, tuple[MotivoEscopo, ...]] | None = None
    evidencia_em: dict[str, Instante] = Field(default_factory=dict)  # tipo do evento -> horario_evidencia esperado
    motivo_evento: dict[str, Texto] = Field(default_factory=dict)  # tipo do evento -> trecho do motivo


class MomentoMeta(Modelo):
    agora: Instante
    ocultar: tuple[Identificador, ...] = ()  # registros externos que ESTA consulta não trouxe (feed truncado)
    esperado: EsperadoMeta | None = None


class ReproducaoMeta(Modelo):
    schema_versao: Literal[1] = 1
    origem: Literal["simulado"]
    descricao: Texto
    meta: Meta
    ativada_em: Instante
    responsavel: Texto
    politica_conciliacao: PoliticaConciliacao
    execucoes: tuple[Execucao, ...] = ()
    registros_externos: tuple[RegistroExterno, ...] = ()
    coberturas_execucoes: tuple[CoberturaExecucoes, ...] = ()
    movimentacoes: tuple[Movimentacao, ...] = ()
    saldos: tuple[SaldoObservado, ...] = ()
    coberturas: tuple[Cobertura, ...] = ()
    vinculos_manuais: tuple[VinculoManual, ...] = ()
    observacoes: tuple[Observacao, ...] = ()
    momentos: Annotated[tuple[MomentoMeta, ...], Field(min_length=1)]


@dataclass
class Passo:
    momento: MomentoMeta
    relatorio: RelatorioConciliacao
    resultado: ResultadoAvaliacao
    reprocessamento_limpo: bool  # reavaliar com o que já foi registrado não gera nenhum evento novo


def carregar_reproducao_meta(caminho: str | Path) -> ReproducaoMeta:
    return carregar_arquivo(ReproducaoMeta, caminho)


def ativacao_de(arquivo: ReproducaoMeta) -> Ativacao:
    return Ativacao(meta_id=arquivo.meta.id, contrato_hash=hash_contrato(arquivo.meta), ativada_em=arquivo.ativada_em, responsavel=arquivo.responsavel)


def _conciliar(arquivo: ReproducaoMeta, agora: datetime, ocultar: tuple[str, ...]) -> RelatorioConciliacao:
    externos = [r for r in arquivo.registros_externos if r.id_externo not in ocultar]
    return conciliar(
        arquivo.execucoes, externos, politica=arquivo.politica_conciliacao, agora=agora, movimentacoes=arquivo.movimentacoes,
        saldos=arquivo.saldos, coberturas=arquivo.coberturas, coberturas_execucoes=arquivo.coberturas_execucoes, vinculos=arquivo.vinculos_manuais,
        metas=[arquivo.meta],
    )


def executar_meta(arquivo: ReproducaoMeta) -> list[Passo]:
    ativacao = ativacao_de(arquivo)
    eventos: list[Evento] = []
    razao: list[EventoConciliacao] = []
    passos: list[Passo] = []
    for momento in sorted(arquivo.momentos, key=lambda m: m.agora):
        relatorio = _conciliar(arquivo, momento.agora, momento.ocultar)
        snapshot = Snapshot(observacoes=tuple(o for o in arquivo.observacoes if o.coletado_em <= momento.agora))
        resultado = avaliar_meta(arquivo.meta, ativacao, eventos, razao, relatorio, snapshot, momento.agora)
        eventos += resultado.eventos
        razao += resultado.eventos_conciliacao
        de_novo = avaliar_meta(arquivo.meta, ativacao, eventos, razao, relatorio, snapshot, momento.agora)
        passos.append(Passo(momento, relatorio, resultado, not de_novo.eventos and not de_novo.eventos_conciliacao))
    return passos


def verificar_passo(passo: Passo) -> list[str]:
    """Discrepâncias entre o resultado e o esperado do momento (lista vazia = ok). Reprocessar sempre tem de ser limpo."""
    problemas: list[str] = []
    if not passo.reprocessamento_limpo:
        problemas.append("reprocessar o mesmo momento gerou eventos novos (duplicação)")
    e = passo.momento.esperado
    if e is None:
        return problemas
    r, p = passo.resultado, passo.resultado.progresso
    if e.estado is not None and r.estado is not e.estado:
        problemas.append(f"estado: esperado {e.estado.value}, obtido {r.estado.value}")
    if e.eventos is not None and tuple(x.tipo.value for x in r.eventos) != e.eventos:
        problemas.append(f"eventos: esperado {list(e.eventos)}, obtido {[x.tipo.value for x in r.eventos]}")
    if e.eventos_conciliacao is not None and tuple(x.tipo.value for x in r.eventos_conciliacao) != e.eventos_conciliacao:
        problemas.append(f"eventos de conciliação: esperado {list(e.eventos_conciliacao)}, obtido {[x.tipo.value for x in r.eventos_conciliacao]}")
    if e.quantidade_comprovada is not None and p.quantidade_comprovada != e.quantidade_comprovada:
        problemas.append(f"quantidade comprovada: esperado {e.quantidade_comprovada}, obtido {p.quantidade_comprovada}")
    if e.quantidade_preservada is not None and p.quantidade_preservada != e.quantidade_preservada:
        problemas.append(f"quantidade preservada: esperado {e.quantidade_preservada}, obtido {p.quantidade_preservada}")
    if e.completa is not None and p.completude.completa is not e.completa:
        problemas.append(f"completa: esperado {e.completa}, obtido {p.completude.completa}")
    if e.elegibilidade is not None and p.elegibilidade.resultado is not e.elegibilidade:
        problemas.append(f"elegibilidade: esperado {e.elegibilidade.value}, obtido {p.elegibilidade.resultado.value}")
    faltam = [m.value for m in e.motivos_elegibilidade if m not in p.elegibilidade.motivos]
    if faltam:
        problemas.append(f"motivos de elegibilidade ausentes: {faltam} (obtido {[m.value for m in p.elegibilidade.motivos]})")
    if e.orcamento is not None and p.orcamento.resultado is not e.orcamento:
        problemas.append(f"orçamento: esperado {e.orcamento.value}, obtido {p.orcamento.resultado.value}")
    if e.bloqueada_por_dados is not None and r.avaliacao.bloqueada_por_dados is not e.bloqueada_por_dados:
        problemas.append(f"bloqueada_por_dados: esperado {e.bloqueada_por_dados}, obtido {r.avaliacao.bloqueada_por_dados}")
    if e.aguardando_evidencia is not None and p.aguardando_evidencia is not e.aguardando_evidencia:
        problemas.append(f"aguardando_evidencia: esperado {e.aguardando_evidencia}, obtido {p.aguardando_evidencia}")
    if e.em_carencia is not None and p.em_carencia is not e.em_carencia:
        problemas.append(f"em_carencia: esperado {e.em_carencia}, obtido {p.em_carencia}")
    if e.orfaos_relevantes is not None and tuple(sorted(o.id_externo for o in p.orfaos if o.relevante)) != tuple(sorted(e.orfaos_relevantes)):
        problemas.append(f"órfãos relevantes: esperado {sorted(e.orfaos_relevantes)}, obtido {sorted(o.id_externo for o in p.orfaos if o.relevante)}")
    if e.orfaos_ignorados is not None:
        obtido = {o.id_externo: o.motivos for o in p.orfaos if not o.relevante}
        if obtido != e.orfaos_ignorados:
            problemas.append(f"órfãos ignorados: esperado {e.orfaos_ignorados}, obtido {obtido}")
    por_tipo = {x.tipo.value: x for x in r.eventos}
    for tipo, instante in e.evidencia_em.items():
        real = por_tipo.get(tipo)
        if real is None or real.horario_evidencia != instante:
            problemas.append(f"evidência de `{tipo}`: esperado {instante}, obtido {real.horario_evidencia if real else 'sem evento'}")
    for tipo, trecho in e.motivo_evento.items():
        real = por_tipo.get(tipo)
        if real is None or trecho not in (real.motivo or ""):
            problemas.append(f"motivo de `{tipo}`: esperava conter {trecho!r}, obtido {real.motivo if real else 'sem evento'!r}")
    return problemas
