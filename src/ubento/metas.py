"""Serviço de metas: a casca entre o núcleo puro, o SQLite e a interface. O relógio entra sempre como parâmetro (`agora`).

Fluxo de cada avaliação: lê contrato, história e entradas do banco → concilia → avalia (núcleo) → grava tudo numa transação.
Nada aqui decide regra de negócio: isso é do núcleo. Aqui só se orquestra, persiste e monta o que a tela mostra.
"""

from __future__ import annotations

import functools
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path

from .nucleo.avaliacao import ProgressoAvaliado, ResultadoAvaliacao, avaliar_meta
from .nucleo.avaliacao.reproducao import MomentoMeta, ReproducaoMeta, ativacao_de, carregar_reproducao_meta
from .nucleo.conciliacao.conciliador import conciliar
from .nucleo.conciliacao.eventos import TipoEventoConciliacao
from .nucleo.conciliacao.modelos import (
    Cobertura, CoberturaExecucoes, Movimentacao, PoliticaConciliacao, RegistroExterno, RevogacaoVinculo, SaldoObservado, VinculoManual,
)
from .nucleo.conciliacao.conciliador import id_do_vinculo
from .nucleo.esquema import Avaliacao, EstadoMeta, Evento, Execucao, LadoExecucao, Meta, Modelo, Observacao
from .nucleo.regras import Snapshot
from .persistencia import ErroBancoOcupado, Repositorio


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
    vinculo: VinculoManual | None = None  # vínculo manual VIGENTE (não revogado)
    historico_vinculos: tuple[tuple[VinculoManual, RevogacaoVinculo | None], ...] = ()  # todos, na ordem, com a revogação de cada um

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
    cenario: bool = True  # True: o instante das avaliações vem do cenário (replay); False: do relógio real, com fuso
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


def _exclusivo(metodo):
    """Executa o método inteiro (verificar, gravar e reavaliar) numa seção de escrita EXCLUSIVA do banco: com dois processos ou threads,
    o segundo espera e enxerga o que o primeiro gravou, então duas alocações simultâneas nunca passam da quantidade do registro e
    a correção + as reavaliações das metas afetadas ficam ou todas gravadas, ou nenhuma."""

    @functools.wraps(metodo)
    def interno(self, *args, **kwargs):
        try:
            with self.repo.escrita():
                return metodo(self, *args, **kwargs)
        except ErroBancoOcupado as erro:  # nada foi gravado; a mensagem é compreensível e o erro técnico já está no log
            raise ErroDeRegistro(str(erro)) from erro

    return interno


@dataclass(frozen=True)
class _Reivindicacao:
    meta_id: str
    execucao_id: str
    alocada: Decimal | None  # None = o registro externo inteiro


def agora_utc() -> datetime:
    return datetime.now(timezone.utc)


class ServicoMetas:
    """`relogio` fornece o horário REAL (com fuso) às metas reais. Metas de cenário (replay) nunca o consultam: o instante vem do cenário.
    Nada avalia sozinho: o relógio só é lido quando alguém pede uma avaliação (registrar, vincular, importar evidência, reavaliar)."""

    def __init__(self, repositorio: Repositorio | None = None, relogio: Callable[[], datetime] = agora_utc):
        self.repo = repositorio or Repositorio()
        self.relogio = relogio

    # -- entrada --------------------------------------------------------------------------------------------------------

    def importar(self, origem: str | Path | ReproducaoMeta, agente_id: str | None = None, cenario: bool = True) -> str:
        """Importa um cenário (dado SIMULADO) e ativa a meta. Idempotente. Devolve o id da meta."""
        arquivo = origem if isinstance(origem, ReproducaoMeta) else carregar_reproducao_meta(origem)
        self.repo.importar(arquivo, ativacao_de(arquivo), agente_id, cenario)
        return arquivo.meta.id

    @_exclusivo
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
        for r in execucao.referencias_externas:
            self._checar_exclusividade((r.fonte_id, r.id_externo), meta_id, execucao.id, r.quantidade_bruta_alocada)
        self.repo.registrar_entrada(meta_id, "execucoes", execucao)
        if execucao.referencias_externas:
            self._reavaliar_afetadas(meta_id, {(r.fonte_id, r.id_externo) for r in execucao.referencias_externas}, execucao.confirmada_em)
        return True

    # -- exclusividade do registro externo (vale entre TODAS as metas do banco; ver docs/PERSISTENCIA_E_INTERFACE.md) ----------------

    def _vinculos_ativos(self, meta_id: str) -> list[VinculoManual]:
        revogados = {r.vinculo_id for r in self.repo.entradas(meta_id, "revogacoes_vinculos", RevogacaoVinculo)}
        return [v for v in self.repo.entradas(meta_id, "vinculos_manuais", VinculoManual) if id_do_vinculo(v) not in revogados]

    def _reivindicacoes(self) -> dict[tuple[str, str], list[_Reivindicacao]]:
        """(fonte, id externo) -> quem o reivindica hoje: referências declaradas e vínculos manuais NÃO revogados, de todas as metas."""
        uso: dict[tuple[str, str], list[_Reivindicacao]] = {}
        for m in self.repo.metas_ids():
            for o in self.repo.entradas(m, "execucoes", Execucao):
                for r in o.referencias_externas:
                    uso.setdefault((r.fonte_id, r.id_externo), []).append(_Reivindicacao(m, o.id, r.quantidade_bruta_alocada))
            for v in self._vinculos_ativos(m):
                uso.setdefault((v.fonte_id, v.id_externo), []).append(_Reivindicacao(m, v.execucao_id, v.quantidade_bruta_alocada))
        return uso

    def _quantidade_do_registro(self, chave: tuple[str, str]) -> Decimal | None:
        melhor: RegistroExterno | None = None
        for m in self.repo.metas_ids():
            for r in self.repo.entradas(m, "registros_externos", RegistroExterno):
                if r.chave == chave and (melhor is None or r.versao >= melhor.versao):
                    melhor = r
        return melhor.quantidade if melhor else None

    def _checar_exclusividade(self, chave: tuple[str, str], meta_id: str, execucao_id: str, alocada: Decimal | None) -> None:
        """Uma compra real (fonte, id externo) é UM fato: nenhuma meta, de qualquer conta, pode contá-la duas vezes.

        Reivindicação integral é exclusiva; reivindicações parciais convivem enquanto a soma das alocações couber na quantidade do registro.
        """
        outras = [c for c in self._reivindicacoes().get(chave, []) if (c.meta_id, c.execucao_id) != (meta_id, execucao_id)]
        if not outras:
            return
        quantidade = self._quantidade_do_registro(chave)
        integral = alocada is None or any(c.alocada is None for c in outras)
        excede = quantidade is not None and sum((c.alocada or Decimal(0) for c in outras), Decimal(0)) + (alocada or Decimal(0)) > quantidade
        if integral or excede:
            dono = outras[0]
            onde = "desta meta" if dono.meta_id == meta_id else f"da meta {dono.meta_id}"
            raise ErroDeRegistro(
                f"o registro externo {chave[0]}/{chave[1]} já está vinculado a outra execução {onde} ({dono.execucao_id}): a mesma compra não pode ser contada duas vezes"
            )

    def registros_disponiveis(self, meta_id: str) -> list[RegistroExterno]:
        """Registros externos importados nesta meta que ainda não pertencem a nenhuma execução de NENHUMA meta (candidatos a vínculo), última versão de cada."""
        uso = self._reivindicacoes()
        ultimos: dict[tuple[str, str], RegistroExterno] = {}
        for r in self.repo.entradas(meta_id, "registros_externos", RegistroExterno):
            if r.chave not in uso and (r.chave not in ultimos or r.versao >= ultimos[r.chave].versao):
                ultimos[r.chave] = r
        return list(ultimos.values())

    @_exclusivo
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
        if any((c.meta_id, c.execucao_id) == (meta_id, execucao_id) for c in self._reivindicacoes().get((fonte_id, id_externo), [])):
            return False  # mesmo vínculo já vigente: nada se duplica
        self._checar_exclusividade((fonte_id, id_externo), meta_id, execucao_id, None)
        em = max(self.instante_de_avaliacao(meta_id), execucao.confirmada_em, *(r.recebido_em for r in registros))
        vinculo = VinculoManual(execucao_id=execucao_id, fonte_id=fonte_id, id_externo=id_externo, autor=autor.strip(), justificativa=justificativa.strip(), em=em)
        self.repo.registrar_entrada(meta_id, "vinculos_manuais", vinculo)
        self.reavaliar(meta_id, em)
        self._reavaliar_afetadas(meta_id, {(fonte_id, id_externo)}, em)
        return True

    # -- correção auditável de vínculos manuais ---------------------------------------------------------------------------------------

    def _reavaliar_afetadas(self, meta_id: str, chaves: set[tuple[str, str]], em: datetime) -> None:
        """Liberar ou disputar um registro externo muda o resultado de TODA meta que o enxerga: as que o reivindicam (disputa que se resolve)
        e as que o têm importado (o registro volta a ser, ou deixa de ser, órfão para elas). Reavalia cada uma que já tinha avaliação."""
        reivindicacoes = self._reivindicacoes()
        for outra in self.repo.metas_ids():
            if outra == meta_id or self.repo.ultima_avaliacao(outra) is None:
                continue
            enxerga = any(c.meta_id == outra for k in chaves for c in reivindicacoes.get(k, [])) or any(
                r.chave in chaves for r in self.repo.entradas(outra, "registros_externos", RegistroExterno)
            )
            if enxerga:
                self.reavaliar(outra, em)

    def _vinculo_vigente(self, meta_id: str, execucao_id: str, fonte_id: str, id_externo: str) -> VinculoManual | None:
        return next((v for v in sorted(self._vinculos_ativos(meta_id), key=lambda v: v.em, reverse=True)
                     if (v.execucao_id, v.fonte_id, v.id_externo) == (execucao_id, fonte_id, id_externo)), None)

    def _exigir_execucao(self, meta_id: str, execucao_id: str) -> Execucao:
        self.repo.carregar_meta(meta_id)
        execucao = next((e for e in self.repo.entradas(meta_id, "execucoes", Execucao) if e.id == execucao_id), None)
        if execucao is None:
            raise ErroDeRegistro(f"a execução {execucao_id} não está registrada nesta meta")
        return execucao

    def _instante_da_correcao(self, meta_id: str, original: VinculoManual) -> datetime:
        """Estritamente depois do vínculo corrigido (a correção nunca reescreve o instante em que ele valia) e nunca antes da última avaliação."""
        return max(self.instante_de_avaliacao(meta_id), original.em + timedelta(seconds=1))

    @_exclusivo
    def revogar_vinculo(self, meta_id: str, execucao_id: str, fonte_id: str, id_externo: str, autor: str, justificativa: str) -> bool:
        """Retira um vínculo manual vigente (porque estava incorreto). O vínculo original é PRESERVADO; a revogação entra no histórico
        com autor, justificativa e instante. Não cria execução nem estorno: só desfaz a correspondência. A conciliação e o estado são
        recalculados pelos mecanismos de sempre (prova contradita vira reversão compensatória; meta atingida segue o caminho de `reconciliada`).
        Devolve False se o vínculo já estava revogado (repetição)."""
        self._exigir_execucao(meta_id, execucao_id)
        alvo = self._vinculo_vigente(meta_id, execucao_id, fonte_id, id_externo)
        if alvo is None:
            if any((v.execucao_id, v.fonte_id, v.id_externo) == (execucao_id, fonte_id, id_externo) for v in self.repo.entradas(meta_id, "vinculos_manuais", VinculoManual)):
                return False
            raise ErroDeRegistro(f"não há vínculo manual de {execucao_id} com {fonte_id}/{id_externo} (uma referência declarada no próprio registro da execução não é revogável aqui)")
        em = self._instante_da_correcao(meta_id, alvo)
        revogacao = RevogacaoVinculo(vinculo_id=id_do_vinculo(alvo), autor=autor.strip(), justificativa=justificativa.strip(), em=em)
        self.repo.registrar_entrada(meta_id, "revogacoes_vinculos", revogacao)
        self.reavaliar(meta_id, em)
        self._reavaliar_afetadas(meta_id, {(fonte_id, id_externo)}, em)
        return True

    @_exclusivo
    def substituir_vinculo(self, meta_id: str, execucao_id: str, fonte_antigo: str, id_antigo: str, fonte_novo: str, id_novo: str,
                           autor: str, justificativa: str) -> bool:
        """Troca o vínculo vigente por outro registro externo: revogação + novo vínculo, gravados juntos (uma transação) e ligados entre si
        (`substituido_por_id`). Valem as mesmas regras de exclusividade do vínculo novo. Devolve False se a troca já foi feita."""
        self._exigir_execucao(meta_id, execucao_id)
        antigo = self._vinculo_vigente(meta_id, execucao_id, fonte_antigo, id_antigo)
        if antigo is None:
            if self._vinculo_vigente(meta_id, execucao_id, fonte_novo, id_novo) is not None:
                return False  # a substituição já aconteceu
            raise ErroDeRegistro(f"não há vínculo manual vigente de {execucao_id} com {fonte_antigo}/{id_antigo} para substituir")
        if (fonte_antigo, id_antigo) == (fonte_novo, id_novo):
            raise ErroDeRegistro("o novo registro externo é o mesmo do vínculo atual: escolha outro (ou revogue)")
        registros = [r for r in self.repo.entradas(meta_id, "registros_externos", RegistroExterno) if r.chave == (fonte_novo, id_novo)]
        if not registros:
            raise ErroDeRegistro(f"o registro externo {fonte_novo}/{id_novo} ainda não foi importado: importe a evidência primeiro")
        self._checar_exclusividade((fonte_novo, id_novo), meta_id, execucao_id, None)
        em = max(self._instante_da_correcao(meta_id, antigo), *(r.recebido_em for r in registros))
        novo = VinculoManual(execucao_id=execucao_id, fonte_id=fonte_novo, id_externo=id_novo, autor=autor.strip(), justificativa=justificativa.strip(), em=em)
        revogacao = RevogacaoVinculo(vinculo_id=id_do_vinculo(antigo), autor=autor.strip(), justificativa=justificativa.strip(), em=em,
                                     substituido_por_id=id_do_vinculo(novo))
        self.repo.registrar_entradas(meta_id, [("revogacoes_vinculos", revogacao), ("vinculos_manuais", novo)])
        self.reavaliar(meta_id, em)
        self._reavaliar_afetadas(meta_id, {(fonte_antigo, id_antigo), (fonte_novo, id_novo)}, em)
        return True

    @_exclusivo
    def importar_evidencia(self, meta_id: str, evidencia: EvidenciaExterna) -> int:
        """Acrescenta registros externos (e coberturas). A prova só passa a valer quando a conciliação os casar com execuções."""
        self.repo.carregar_meta(meta_id)
        novos = 0
        for r in evidencia.registros_externos:
            novos += self.repo.registrar_entrada(meta_id, "registros_externos", r)
        for c in evidencia.coberturas_execucoes:
            novos += self.repo.registrar_entrada(meta_id, "coberturas_execucoes", c)
        return novos

    def _agora_real(self) -> datetime:
        agora = self.relogio()
        if agora.tzinfo is None or agora.utcoffset() is None:
            raise ValueError("o relógio precisa devolver um horário com fuso explícito (ex.: UTC)")
        return agora.astimezone(timezone.utc)

    def instante_de_avaliacao(self, meta_id: str, no_minimo: datetime | None = None) -> datetime:
        """De onde vem o `agora` de uma avaliação pedida:
          - meta de CENÁRIO (replay): o instante do cenário (o mais tardio entre a última avaliação e `no_minimo`); o relógio do sistema não é lido;
          - meta REAL: o horário real (UTC), nunca antes da última avaliação (o tempo das avaliações não anda para trás) nem de `no_minimo`."""
        ultima = self.repo.ultima_avaliacao(meta_id)
        base = [i for i in (ultima[0].avaliada_em if ultima else None, no_minimo) if i is not None]
        if self.repo.meta_e_cenario(meta_id):
            return max(base, default=self.repo.carregar_meta(meta_id)[1].ativada_em)
        return max([self._agora_real(), *base])

    def reavaliar(self, meta_id: str, no_minimo: datetime | None = None) -> ResultadoAvaliacao:
        """Reavalia no instante dado por `instante_de_avaliacao` (relógio real nas metas reais, instante do cenário nos replays)."""
        return self.avaliar(meta_id, self.instante_de_avaliacao(meta_id, no_minimo))

    # -- avaliação ------------------------------------------------------------------------------------------------------

    def _insumos_conjuntos(self, meta_id: str, ocultar: tuple[str, ...]):
        """Entradas da conciliação: as da meta + as execuções (e vínculos) das OUTRAS metas, para que o núcleo enxergue uma mesma compra
        reivindicada duas vezes (vira revisão nas duas, nunca progresso em dobro). Os ids das outras metas ganham prefixo: o núcleo trata
        o id da execução como global e metas diferentes podem repetir ids. Das outras metas entram só os registros externos que elas reivindicam."""
        r = self.repo
        execucoes = list(r.entradas(meta_id, "execucoes", Execucao))
        externos = [x for x in r.entradas(meta_id, "registros_externos", RegistroExterno) if x.id_externo not in ocultar]
        vinculos = list(r.entradas(meta_id, "vinculos_manuais", VinculoManual))
        revogacoes = list(r.entradas(meta_id, "revogacoes_vinculos", RevogacaoVinculo))
        coberturas = list(r.entradas(meta_id, "coberturas_execucoes", CoberturaExecucoes))
        metas = [r.carregar_meta(meta_id)[0]]
        for outra in r.metas_ids():
            if outra == meta_id:
                continue
            execs = r.entradas(outra, "execucoes", Execucao)
            if not execs:
                continue
            pre = f"{outra}::"
            metas.append(r.carregar_meta(outra)[0])  # o contexto (ativo, moeda, mercado, conta) de cada meta que entra na conciliação
            execucoes += [e.model_copy(update={"id": pre + e.id, "estorna_execucao_id": pre + e.estorna_execucao_id if e.estorna_execucao_id else None}) for e in execs]
            novos_ids: dict[str, str] = {}
            vinculos_outra = []
            for v in r.entradas(outra, "vinculos_manuais", VinculoManual):
                v2 = v.model_copy(update={"execucao_id": pre + v.execucao_id})
                novos_ids[id_do_vinculo(v)] = id_do_vinculo(v2)
                vinculos_outra.append(v2)
            vinculos += vinculos_outra
            for rv in r.entradas(outra, "revogacoes_vinculos", RevogacaoVinculo):
                revogacoes.append(rv.model_copy(update={
                    "vinculo_id": novos_ids.get(rv.vinculo_id, rv.vinculo_id),
                    "substituido_por_id": novos_ids.get(rv.substituido_por_id, rv.substituido_por_id) if rv.substituido_por_id else None,
                }))
            chaves = {(x.fonte_id, x.id_externo) for e in execs for x in e.referencias_externas} | {(v.fonte_id, v.id_externo) for v in vinculos_outra}
            externos += [x for x in r.entradas(outra, "registros_externos", RegistroExterno) if x.chave in chaves]
            coberturas += r.entradas(outra, "coberturas_execucoes", CoberturaExecucoes)
        return execucoes, externos, vinculos, revogacoes, coberturas, metas

    def avaliar(self, meta_id: str, agora: datetime, ocultar: tuple[str, ...] = ()) -> ResultadoAvaliacao:
        meta, ativacao = self.repo.carregar_meta(meta_id)
        r = self.repo
        execucoes, externos, vinculos, revogacoes, coberturas_execucoes, metas = self._insumos_conjuntos(meta_id, ocultar)
        politica = r.entradas(meta_id, "politica_conciliacao", PoliticaConciliacao)[-1]  # a política mais recente (reimportar um cenário a atualiza)
        relatorio = conciliar(
            execucoes, externos, politica=politica, agora=agora,
            movimentacoes=r.entradas(meta_id, "movimentacoes", Movimentacao), saldos=r.entradas(meta_id, "saldos", SaldoObservado),
            coberturas=r.entradas(meta_id, "coberturas", Cobertura), coberturas_execucoes=coberturas_execucoes,
            vinculos=vinculos, revogacoes=revogacoes, metas=metas,
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
        revogacoes = {rv.vinculo_id: rv for rv in self.repo.entradas(meta_id, "revogacoes_vinculos", RevogacaoVinculo)}
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
            historico = tuple((v, revogacoes.get(id_do_vinculo(v))) for v in vinculos if v.execucao_id == ex.id)
            vigente = next((v for v, rv in reversed(historico) if rv is None), None)
            registradas.append(ExecucaoRegistrada(ex, situacao, vigente, historico))
        return PainelMeta(
            meta_id=meta_id, descricao=self.repo.descricao(meta_id), agente_id=self.repo.agente_da_meta(meta_id),
            estado=ultima[0].estado if ultima else None, avaliacao=ultima[0] if ultima else None, progresso=ultima[1] if ultima else None,
            eventos=tuple(self.repo.eventos(meta_id)), execucoes=tuple(registradas), moeda_cotacao_id=meta.objetivo.moeda_cotacao_id, momentos_total=len(self.repo.momentos(meta_id)),
            proximo_momento=self.repo.cursor(meta_id), ativo_id=_ativo(meta), prazo=meta.objetivo.prazo, cenario=self.repo.meta_e_cenario(meta_id),
        )


def _ativo(meta: Meta) -> str:
    return meta.objetivo.ativo_id
