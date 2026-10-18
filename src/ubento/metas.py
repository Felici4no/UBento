"""Serviço de metas: a casca entre o núcleo puro, o SQLite e a interface. O relógio entra sempre como parâmetro (`agora`).

Fluxo de cada avaliação: lê contrato, história e entradas do banco → concilia → avalia (núcleo) → grava tudo numa transação.
Nada aqui decide regra de negócio: isso é do núcleo. Aqui só se orquestra, persiste e monta o que a tela mostra.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from pathlib import Path

from .nucleo.avaliacao import ProgressoAvaliado, ResultadoAvaliacao, avaliar_meta
from .nucleo.avaliacao.reproducao import MomentoMeta, ReproducaoMeta, ativacao_de, carregar_reproducao_meta
from .nucleo.conciliacao.conciliador import conciliar
from .nucleo.conciliacao.eventos import TipoEventoConciliacao
from .nucleo.conciliacao.modelos import (
    Cobertura, CoberturaExecucoes, Movimentacao, PoliticaConciliacao, RegistroExterno, SaldoObservado, VinculoManual,
)
from .nucleo.esquema import Avaliacao, EstadoMeta, Evento, Execucao, LadoExecucao, Meta, Modelo, Observacao
from .nucleo.regras import Snapshot
from .persistencia import Repositorio


class ErroDeRegistro(ValueError):
    """Registro recusado (duplicado, conflitante ou incoerente com a meta). A mensagem é pensada para ser mostrada ao usuário."""


class EvidenciaExterna(Modelo):
    """Arquivo de evidência: registros reportados por uma fonte externa (+ cobertura da consulta, se a fonte a declara)."""

    registros_externos: tuple[RegistroExterno, ...] = ()
    coberturas_execucoes: tuple[CoberturaExecucoes, ...] = ()


# Situação de uma execução REGISTRADA. Registrar (confirmação interna) nunca é prova; a prova vem do registro externo conciliado.
NAO_AVALIADA, PENDENTE_DE_COMPROVACAO, COMPROVADA, REVERTIDA = "nao_avaliada", "pendente_de_comprovacao", "comprovada", "revertida"


@dataclass(frozen=True)
class ExecucaoRegistrada:
    execucao: Execucao
    situacao: str
    vinculo: VinculoManual | None = None  # decisão humana que ligou a execução a um registro externo depois

    @property
    def sem_referencia_externa(self) -> bool:
        return not self.execucao.referencias_externas and self.vinculo is None


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
    execucoes: tuple[ExecucaoRegistrada, ...]
    moeda_cotacao_id: str
    momentos_total: int
    proximo_momento: int
    ativo_id: str
    prazo: datetime
    fonte_simulada: bool = True

    @property
    def quantidade_registrada_pendente(self) -> Decimal:
        """Líquida das execuções registradas que ainda não foram comprovadas (estorno subtrai). NÃO é progresso."""
        return sum(
            (-r.execucao.quantidade_liquida if r.execucao.lado is LadoExecucao.ESTORNO_COMPRA else r.execucao.quantidade_liquida
             for r in self.execucoes if r.situacao == PENDENTE_DE_COMPROVACAO), Decimal(0),
        )

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

    def registrar_execucao(self, meta_id: str, execucao: Execucao) -> bool:
        """Registro SEPARADO de uma operação confirmada. É só aqui (e nunca na aprovação) que uma execução passa a existir.

        Registrar NÃO comprova: a execução fica pendente até existir registro externo correspondente. Devolve False se a mesma
        execução (mesmos dados) já estava registrada (nada é duplicado) e levanta `ErroDeRegistro` se for conflitante.
        """
        meta, _ = self.repo.carregar_meta(meta_id)
        if execucao.meta_id != meta_id:
            raise ErroDeRegistro("a execução pertence a outra meta")
        if execucao.ativo_id != meta.objetivo.ativo_id:
            raise ErroDeRegistro(f"o ativo da execução ({execucao.ativo_id}) não é o ativo da meta ({meta.objetivo.ativo_id})")
        existentes = self.repo.entradas(meta_id, "execucoes", Execucao)
        for outra in existentes:
            if outra == execucao:
                return False
            if outra.id == execucao.id:
                raise ErroDeRegistro(f"o identificador {execucao.id} já existe com outros dados. Registros não são editados: use outro identificador (ou um estorno)")
        if execucao.lado is LadoExecucao.ESTORNO_COMPRA:
            original = next((o for o in existentes if o.id == execucao.estorna_execucao_id), None)
            if original is None or original.lado is not LadoExecucao.COMPRA:
                raise ErroDeRegistro(f"o estorno aponta para {execucao.estorna_execucao_id}, que não é uma compra registrada nesta meta")
        usadas = self._referencias_em_uso(meta_id)
        for r in execucao.referencias_externas:
            outros = usadas.get((r.fonte_id, r.id_externo), [])
            if any(alocada is None or r.quantidade_bruta_alocada is None for _, alocada in outros):
                raise ErroDeRegistro(f"o registro externo {r.fonte_id}/{r.id_externo} já está vinculado a outra execução desta meta")
        self.repo.registrar_entrada(meta_id, "execucoes", execucao)
        return True

    def _referencias_em_uso(self, meta_id: str) -> dict[tuple[str, str], list[tuple[str, object]]]:
        """(fonte, id externo) -> [(execução, alocação)] pelas referências declaradas E pelos vínculos manuais."""
        uso: dict[tuple[str, str], list[tuple[str, object]]] = {}
        for o in self.repo.entradas(meta_id, "execucoes", Execucao):
            for r in o.referencias_externas:
                uso.setdefault((r.fonte_id, r.id_externo), []).append((o.id, r.quantidade_bruta_alocada))
        for v in self.repo.entradas(meta_id, "vinculos_manuais", VinculoManual):
            uso.setdefault((v.fonte_id, v.id_externo), []).append((v.execucao_id, v.quantidade_bruta_alocada))
        return uso

    def registros_disponiveis(self, meta_id: str) -> list[RegistroExterno]:
        """Registros externos importados que ainda não pertencem a nenhuma execução da meta (candidatos a vínculo manual), última versão de cada."""
        uso = self._referencias_em_uso(meta_id)
        ultimos: dict[tuple[str, str], RegistroExterno] = {}
        for r in self.repo.entradas(meta_id, "registros_externos", RegistroExterno):
            if r.chave not in uso and (r.chave not in ultimos or r.versao >= ultimos[r.chave].versao):
                ultimos[r.chave] = r
        return list(ultimos.values())

    def vincular_manualmente(self, meta_id: str, execucao_id: str, fonte_id: str, id_externo: str, autor: str, justificativa: str) -> bool:
        """Liga, DEPOIS, uma execução registrada a um registro externo já importado (decisão humana, com autor e justificativa).

        Não edita a execução: acrescenta um `VinculoManual` ao histórico. O vínculo vale a partir de `em` (o instante de referência:
        o mais tardio entre a última avaliação, a confirmação da execução e o recebimento do registro). Devolve False se esse mesmo
        vínculo já existe; levanta `ErroDeRegistro` se a execução ou o registro não existem, ou se o registro já pertence a outra execução.
        A comprovação continua sendo decidida pela conciliação: o vínculo só diz QUAL registro externo corresponde.
        """
        self.repo.carregar_meta(meta_id)
        execucao = next((e for e in self.repo.entradas(meta_id, "execucoes", Execucao) if e.id == execucao_id), None)
        if execucao is None:
            raise ErroDeRegistro(f"a execução {execucao_id} não está registrada nesta meta")
        registros = [r for r in self.repo.entradas(meta_id, "registros_externos", RegistroExterno) if r.chave == (fonte_id, id_externo)]
        if not registros:
            raise ErroDeRegistro(f"o registro externo {fonte_id}/{id_externo} ainda não foi importado: importe a evidência primeiro")
        if any((r.fonte_id, r.id_externo) == (fonte_id, id_externo) for r in execucao.referencias_externas):
            return False  # a execução já declarava essa referência
        usados = self._referencias_em_uso(meta_id).get((fonte_id, id_externo), [])
        if any(dono == execucao_id for dono, _ in usados):
            return False  # mesmo vínculo já registrado: nada se duplica
        if usados:
            raise ErroDeRegistro(f"o registro externo {fonte_id}/{id_externo} já está vinculado a outra execução desta meta ({usados[0][0]})")
        ultima = self.repo.ultima_avaliacao(meta_id)
        em = max(i for i in (ultima[0].avaliada_em if ultima else None, execucao.confirmada_em, *(r.recebido_em for r in registros)) if i is not None)
        vinculo = VinculoManual(execucao_id=execucao_id, fonte_id=fonte_id, id_externo=id_externo, autor=autor.strip(), justificativa=justificativa.strip(), em=em)
        self.repo.registrar_entrada(meta_id, "vinculos_manuais", vinculo)
        self.reavaliar(meta_id, em)
        return True

    def importar_evidencia(self, meta_id: str, evidencia: EvidenciaExterna) -> int:
        """Acrescenta registros externos (e coberturas). A prova só passa a valer quando a conciliação os casar com execuções."""
        self.repo.carregar_meta(meta_id)
        novos = 0
        for r in evidencia.registros_externos:
            novos += self.repo.registrar_entrada(meta_id, "registros_externos", r)
        for c in evidencia.coberturas_execucoes:
            novos += self.repo.registrar_entrada(meta_id, "coberturas_execucoes", c)
        return novos

    def reavaliar(self, meta_id: str, no_minimo: datetime | None = None) -> ResultadoAvaliacao:
        """Reavalia no instante de referência: o mais tardio entre a última avaliação e `no_minimo` (nunca o relógio do sistema)."""
        ultima = self.repo.ultima_avaliacao(meta_id)
        instantes = [i for i in (ultima[0].avaliada_em if ultima else None, no_minimo) if i is not None]
        _, ativacao = self.repo.carregar_meta(meta_id)
        return self.avaliar(meta_id, max(instantes, default=ativacao.ativada_em))

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
        razao = self.repo.razao(meta_id)
        pendentes = {pe.referencia for pe in ultima[1].completude.pendencias} if ultima else set()
        registradas = []
        vinculos = self.repo.entradas(meta_id, "vinculos_manuais", VinculoManual)
        for ex in self.repo.entradas(meta_id, "execucoes", Execucao):
            eventos_ex = [e for e in razao if e.alvo == ex.id]
            if eventos_ex and eventos_ex[-1].tipo is TipoEventoConciliacao.EXECUCAO_CONCILIADA:
                situacao = COMPROVADA
            elif eventos_ex and eventos_ex[-1].tipo is TipoEventoConciliacao.CONCILIACAO_REVERTIDA:
                situacao = REVERTIDA
            elif ultima is not None and (ex.id in pendentes or not eventos_ex):
                situacao = PENDENTE_DE_COMPROVACAO
            else:
                situacao = NAO_AVALIADA
            registradas.append(ExecucaoRegistrada(ex, situacao, next((v for v in reversed(vinculos) if v.execucao_id == ex.id), None)))
        return PainelMeta(
            meta_id=meta_id, descricao=self.repo.descricao(meta_id), agente_id=self.repo.agente_da_meta(meta_id),
            estado=ultima[0].estado if ultima else None, avaliacao=ultima[0] if ultima else None, progresso=ultima[1] if ultima else None,
            eventos=tuple(self.repo.eventos(meta_id)), execucoes=tuple(registradas), moeda_cotacao_id=meta.objetivo.moeda_cotacao_id, momentos_total=len(self.repo.momentos(meta_id)),
            proximo_momento=self.repo.cursor(meta_id), ativo_id=_ativo(meta), prazo=meta.objetivo.prazo,
        )


def _ativo(meta: Meta) -> str:
    return meta.objetivo.ativo_id
