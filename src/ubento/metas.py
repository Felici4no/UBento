"""Serviço de metas: a casca entre o núcleo puro, o SQLite e a interface. O relógio entra sempre como parâmetro (`agora`).

Fluxo de cada avaliação: lê contrato, história e entradas do banco → concilia → avalia (núcleo) → grava tudo numa transação.
Nada aqui decide regra de negócio: isso é do núcleo. Aqui só se orquestra, persiste e monta o que a tela mostra.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from .nucleo.avaliacao import ProgressoAvaliado, ResultadoAvaliacao, avaliar_meta
from .nucleo.avaliacao.reproducao import MomentoMeta, ReproducaoMeta, ativacao_de, carregar_reproducao_meta
from .nucleo.conciliacao.conciliador import conciliar
from .nucleo.conciliacao.modelos import (
    Cobertura, CoberturaExecucoes, Movimentacao, PoliticaConciliacao, RegistroExterno, SaldoObservado, VinculoManual,
)
from .nucleo.esquema import Avaliacao, EstadoMeta, Evento, Execucao, Meta, Observacao
from .nucleo.regras import Snapshot
from .persistencia import Repositorio


@dataclass(frozen=True)
class PainelMeta:
    """O que a tela mostra de uma meta. Quatro grandezas separadas; nada é fundido num número só."""

    meta_id: str
    descricao: str
    agente_id: str | None
    estado: EstadoMeta | None  # None = ainda não avaliada
    avaliacao: Avaliacao | None
    progresso: ProgressoAvaliado | None
    eventos: tuple[Evento, ...]
    momentos_total: int
    proximo_momento: int
    ativo_id: str
    prazo: datetime
    fonte_simulada: bool = True

    @property
    def pode_avancar(self) -> bool:
        return self.proximo_momento < self.momentos_total


class ServicoMetas:
    def __init__(self, repositorio: Repositorio | None = None):
        self.repo = repositorio or Repositorio()

    # -- entrada --------------------------------------------------------------------------------------------------------

    def importar(self, origem: str | Path | ReproducaoMeta, agente_id: str | None = None) -> str:
        """Importa um cenário (dado SIMULADO) e ativa a meta. Idempotente. Devolve o id da meta."""
        arquivo = origem if isinstance(origem, ReproducaoMeta) else carregar_reproducao_meta(origem)
        self.repo.importar(arquivo, ativacao_de(arquivo), agente_id)
        return arquivo.meta.id

    def registrar_execucao(self, meta_id: str, execucao: Execucao) -> None:
        """Registro SEPARADO de uma operação confirmada. É só aqui (e nunca na aprovação) que uma execução passa a existir."""
        if execucao.meta_id != meta_id:
            raise ValueError("a execução pertence a outra meta")
        self.repo.registrar_entrada(meta_id, "execucoes", execucao)

    # -- avaliação ------------------------------------------------------------------------------------------------------

    def avaliar(self, meta_id: str, agora: datetime, ocultar: tuple[str, ...] = ()) -> ResultadoAvaliacao:
        meta, ativacao = self.repo.carregar_meta(meta_id)
        r = self.repo
        externos = [x for x in r.entradas(meta_id, "registros_externos", RegistroExterno) if x.id_externo not in ocultar]
        politica = r.entradas(meta_id, "politica_conciliacao", PoliticaConciliacao)[0]
        relatorio = conciliar(
            r.entradas(meta_id, "execucoes", Execucao), externos, politica=politica, agora=agora,
            movimentacoes=r.entradas(meta_id, "movimentacoes", Movimentacao), saldos=r.entradas(meta_id, "saldos", SaldoObservado),
            coberturas=r.entradas(meta_id, "coberturas", Cobertura),
            coberturas_execucoes=r.entradas(meta_id, "coberturas_execucoes", CoberturaExecucoes),
            vinculos=r.entradas(meta_id, "vinculos_manuais", VinculoManual),
        )
        snapshot = Snapshot(observacoes=tuple(o for o in r.entradas(meta_id, "observacoes", Observacao) if o.coletado_em <= agora))
        resultado = avaliar_meta(meta, ativacao, r.eventos(meta_id), r.razao(meta_id), relatorio, snapshot, agora)
        r.gravar(meta_id, resultado)
        return resultado

    def avancar(self, meta_id: str) -> tuple[MomentoMeta, ResultadoAvaliacao] | None:
        """Avalia o próximo momento do cenário. Devolve None se não restam momentos."""
        momentos = self.repo.momentos(meta_id)
        i = self.repo.cursor(meta_id)
        if i >= len(momentos):
            return None
        momento = momentos[i]
        resultado = self.avaliar(meta_id, momento.agora, momento.ocultar)
        self.repo.mover_cursor(meta_id, i + 1)
        return momento, resultado

    # -- leitura --------------------------------------------------------------------------------------------------------

    def metas(self, agente_id: str | None = None) -> list[str]:
        return [m for m in self.repo.metas_ids() if agente_id is None or self.repo.agente_da_meta(m) == agente_id]

    def painel(self, meta_id: str) -> PainelMeta:
        meta, _ = self.repo.carregar_meta(meta_id)
        ultima = self.repo.ultima_avaliacao(meta_id)
        return PainelMeta(
            meta_id=meta_id, descricao=self.repo.descricao(meta_id), agente_id=self.repo.agente_da_meta(meta_id),
            estado=ultima[0].estado if ultima else None, avaliacao=ultima[0] if ultima else None, progresso=ultima[1] if ultima else None,
            eventos=tuple(self.repo.eventos(meta_id)), momentos_total=len(self.repo.momentos(meta_id)),
            proximo_momento=self.repo.cursor(meta_id), ativo_id=_ativo(meta), prazo=meta.objetivo.prazo,
        )


def _ativo(meta: Meta) -> str:
    return meta.objetivo.ativo_id
