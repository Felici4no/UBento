"""Arquivos de reprodução: cenários de conciliação gravados em YAML/JSON, sempre marcados como simulados.

Um arquivo reúne todos os registros (cada um com o seu `recebido_em`) e uma lista de `momentos`. Em cada momento o
conciliador enxerga só o que já tinha chegado até `agora`, o que permite reproduzir dados atrasados e correções.
"""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Annotated, Literal

from pydantic import Field

from ..carregador import carregar_arquivo
from ..esquema import Execucao, Modelo
from ..tipos import Identificador, Instante, Numero, Texto
from .conciliador import conciliar
from .eventos import EventoConciliacao, diferenciar
from .modelos import (
    Cobertura, CoberturaExecucoes, Confirmacao, Motivo, Movimentacao, PoliticaConciliacao, RegistroExterno, RelatorioConciliacao,
    SaldoObservado, StatusConciliacao, StatusSaldo, VinculoManual,
)


class Esperado(Modelo):
    """Resultado que o cenário afirma para um momento (usado como teste de regressão)."""

    execucoes: dict[Identificador, StatusConciliacao] = Field(default_factory=dict)
    motivos: dict[Identificador, tuple[Motivo, ...]] = Field(default_factory=dict)  # cada um deve estar presente
    comprovado: dict[Identificador, Numero] = Field(default_factory=dict)  # por meta
    declarado: dict[Identificador, Numero] = Field(default_factory=dict)
    confirmacao: Confirmacao | None = None
    orfaos: tuple[Identificador, ...] | None = None
    saldos: dict[Identificador, StatusSaldo] = Field(default_factory=dict)  # por ativo (primeiro intervalo)
    eventos: tuple[str, ...] | None = None  # tipos, na ordem


class Momento(Modelo):
    agora: Instante
    esperado: Esperado | None = None


class ArquivoReproducao(Modelo):
    schema_versao: Literal[1] = 1
    origem: Literal["simulado"]  # arquivos de reprodução nunca se passam por dados reais
    descricao: Texto
    politica: PoliticaConciliacao
    execucoes: tuple[Execucao, ...] = ()
    registros_externos: tuple[RegistroExterno, ...] = ()
    movimentacoes: tuple[Movimentacao, ...] = ()
    saldos: tuple[SaldoObservado, ...] = ()
    coberturas: tuple[Cobertura, ...] = ()
    coberturas_execucoes: tuple[CoberturaExecucoes, ...] = ()
    vinculos_manuais: tuple[VinculoManual, ...] = ()
    momentos: Annotated[tuple[Momento, ...], Field(min_length=1)]


def carregar_reproducao(caminho: str | Path) -> ArquivoReproducao:
    return carregar_arquivo(ArquivoReproducao, caminho)


def executar_momento(arquivo: ArquivoReproducao, agora: datetime) -> RelatorioConciliacao:
    return conciliar(
        arquivo.execucoes, arquivo.registros_externos, politica=arquivo.politica, agora=agora,
        movimentacoes=arquivo.movimentacoes, saldos=arquivo.saldos, coberturas=arquivo.coberturas,
        coberturas_execucoes=arquivo.coberturas_execucoes, vinculos=arquivo.vinculos_manuais,
    )


def executar(arquivo: ArquivoReproducao) -> list[tuple[Momento, RelatorioConciliacao, tuple[EventoConciliacao, ...]]]:
    """Roda todos os momentos em ordem cronológica, encadeando os eventos compensatórios entre relatórios."""
    saida, anterior = [], None
    for momento in sorted(arquivo.momentos, key=lambda m: m.agora):
        relatorio = executar_momento(arquivo, momento.agora)
        saida.append((momento, relatorio, diferenciar(anterior, relatorio)))
        anterior = relatorio
    return saida


def verificar(momento: Momento, relatorio: RelatorioConciliacao, eventos: tuple[EventoConciliacao, ...]) -> list[str]:
    """Compara o relatório com o `esperado` do momento. Devolve a lista de discrepâncias (vazia = ok)."""
    e = momento.esperado
    if e is None:
        return []
    problemas: list[str] = []
    por_id = {r.execucao_id: r for r in relatorio.execucoes}
    for id_, status in e.execucoes.items():
        real = por_id.get(id_)
        if real is None or real.status is not status:
            problemas.append(f"execução {id_}: esperado {status.value}, obtido {real.status.value if real else 'ausente'}")
    for id_, motivos in e.motivos.items():
        real = por_id.get(id_)
        faltam = [m.value for m in motivos if real is None or m not in real.motivos]
        if faltam:
            problemas.append(f"execução {id_}: faltam motivos {faltam}")
    progresso = {p.meta_id: p for p in relatorio.progresso}
    for meta, valor in e.comprovado.items():
        real = progresso[meta].comprovado if meta in progresso else None
        if real != valor:
            problemas.append(f"meta {meta}: comprovado esperado {valor}, obtido {real}")
    for meta, valor in e.declarado.items():
        real = progresso[meta].declarado if meta in progresso else None
        if real != valor:
            problemas.append(f"meta {meta}: declarado esperado {valor}, obtido {real}")
    if e.confirmacao is not None and relatorio.confirmacao is not e.confirmacao:
        problemas.append(f"confirmação: esperado {e.confirmacao.value}, obtido {relatorio.confirmacao.value}")
    if e.orfaos is not None and tuple(sorted(o.id_externo for o in relatorio.orfaos)) != tuple(sorted(e.orfaos)):
        problemas.append(f"órfãos: esperado {sorted(e.orfaos)}, obtido {sorted(o.id_externo for o in relatorio.orfaos)}")
    for ativo, status in e.saldos.items():
        real = next((s for s in relatorio.saldos if s.ativo_id == ativo), None)
        if real is None or real.status is not status:
            problemas.append(f"saldo {ativo}: esperado {status.value}, obtido {real.status.value if real else 'ausente'}")
    if e.eventos is not None and tuple(ev.tipo.value for ev in eventos) != tuple(e.eventos):
        problemas.append(f"eventos: esperado {list(e.eventos)}, obtido {[ev.tipo.value for ev in eventos]}")
    return problemas


