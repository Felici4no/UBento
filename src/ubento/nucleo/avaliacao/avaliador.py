"""Avaliador de metas (D3): execuções → conciliação → progresso → avaliação → eventos.

Função pura. O estado é função da evidência; os eventos são a diferença entre o estado já registrado e o que a
evidência mostra agora. Por isso reprocessar nunca duplica nada: se nada mudou, não há evento novo.

Política (docs/AVALIACAO_META.md):
  - atingida: quantidade líquida comprovada >= alvo, dentro da janela [ativação, prazo], e elegibilidade verdadeira;
  - expirada: depois do prazo; se ainda há evidência que poderia fechar a meta, espera a carência (só para receber
    evidência: não estende o prazo de compras) e expira com `prazo_sem_evidencia`;
  - invalidada: alguma condição de invalidação observada;
  - precedência: vale o menor instante de EVIDÊNCIA; empate pela `ordem_empate` congelada no contrato;
  - correção posterior (estorno, cancelamento externo, evidência tardia): evento `reconciliada`, que preserva a
    conclusão anterior na história e recalcula o estado. `cancelada` é ato humano e nunca é recalculada.
"""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Sequence

from ..canonico import hash_canonico, hash_contrato
from ..conciliacao.eventos import EventoConciliacao, TipoEventoConciliacao, compensar
from ..conciliacao.modelos import RelatorioConciliacao
from ..esquema import Ativacao, Avaliacao, EstadoMeta, Evento, Meta, ResultadoCondicao, TipoEvento
from ..regras import Snapshot, avaliar_grupo, evidencia_da_condicao
from ..tipos import Tri, formatar_instante, normalizar_decimal
from .estado import RECONCILIAVEIS, bloqueada_por_dados, estado_de, sequencia_do_ultimo_estado, ultima_sequencia, validar_historico
from .modelos import AUTOR_SISTEMA, VERSAO_MOTOR, MotivoAvaliacao, ResultadoAvaliacao
from .progresso import analisar_progresso

DOMINIO_EVENTO = "ubento.evento.meta.v1"
DOMINIO_ENTRADAS = "ubento.avaliacao.entradas.v1"
DOMINIO_SAIDA = "ubento.avaliacao.saida.v1"


class ErroDeAvaliacao(ValueError):
    """Entradas incoerentes (contrato diferente do ativado, avaliação antes da ativação…)."""


def avaliar_meta(
    meta: Meta,
    ativacao: Ativacao,
    eventos: Sequence[Evento],
    razao: Sequence[EventoConciliacao],
    relatorio: RelatorioConciliacao,
    snapshot: Snapshot,
    agora: datetime,
) -> ResultadoAvaliacao:
    """Avalia a meta em `agora`. `eventos` e `razao` são o que já foi registrado; o resultado traz só o que é NOVO."""
    if ativacao.meta_id != meta.id or ativacao.contrato_hash != hash_contrato(meta):
        raise ErroDeAvaliacao("o contrato apresentado não é o que foi ativado (hash diferente): metas ativas são imutáveis")
    if agora < ativacao.ativada_em:
        raise ErroDeAvaliacao("avaliação anterior à ativação")

    historia = validar_historico(meta.id, eventos)
    conhecidos = {e.id for e in historia}
    novos: list[Evento] = []
    proxima = [ultima_sequencia(historia) + 1]

    def emitir(tipo: TipoEvento, horario: datetime, chave: str, *, motivo: str | None = None, autor: str | None = None,
               dados: dict | None = None, idempotencia: str | None = None) -> Evento | None:
        ident = hash_canonico({"meta": meta.id, "tipo": tipo.value, "chave": chave}, DOMINIO_EVENTO)
        if ident in conhecidos:
            return None
        evento = Evento(id=ident, meta_id=meta.id, sequencia=proxima[0], tipo=tipo, horario_evidencia=horario, registrado_em=max(agora, horario),
                        autor=autor, motivo=motivo, chave_idempotencia=idempotencia, dados=dados or {})
        proxima[0] += 1
        conhecidos.add(ident)
        novos.append(evento)
        return evento

    if not historia:
        emitir(TipoEvento.ATIVADA, ativacao.ativada_em, ativacao.contrato_hash, autor=ativacao.responsavel)
    estado_antes = estado_de([*historia, *novos], meta.id)
    sequencia_estado = sequencia_do_ultimo_estado([*historia, *novos])

    # 1) conciliação → razão → progresso
    novos_conc, efeitos = compensar(razao, relatorio, meta.id)
    progresso = analisar_progresso(meta, ativacao, relatorio, efeitos, agora)
    prazo = meta.objetivo.prazo
    carencia = timedelta(seconds=meta.politicas.carencia_dados_segundos)

    # 2) regras do contrato sobre o snapshot de dados
    validades = {v.metrica_id: v.validade_maxima_segundos for v in meta.politicas.validades}
    tolerancias = {(t.metrica_id, t.mercado_id): t for t in meta.politicas.tolerancias}
    bloqueios, r_bloq = avaliar_grupo(meta.regras.bloqueios, snapshot, agora, validades, tolerancias, "todos")
    invalidacao, r_inv = avaliar_grupo(meta.regras.invalidacao, snapshot, agora, validades, tolerancias, "algum")
    entrada, r_ent = avaliar_grupo(meta.regras.entrada, snapshot, agora, validades, tolerancias, "todos")
    resultados_regras: list[ResultadoCondicao] = [*r_bloq, *r_inv, *r_ent]
    bloqueada = any(r.resultado is Tri.INDETERMINADO for r in resultados_regras)

    # 3) candidatos a estado final, cada um com o instante da EVIDÊNCIA
    candidatos: list[tuple[datetime, str, EstadoMeta, dict]] = []
    if progresso.elegibilidade.resultado is Tri.VERDADEIRO and progresso.instante_atingimento is not None:
        candidatos.append((progresso.instante_atingimento, "atingida", EstadoMeta.ATINGIDA, {"motivo": "objetivo_comprovado"}))

    elif (estado_antes is EstadoMeta.ATINGIDA and progresso.elegibilidade.resultado is Tri.INDETERMINADO
          and progresso.instante_atingimento is not None):
        # pendência é possibilidade, não prova: só uma redução COMPROVADA (ou um limite comprovadamente violado) reabre a meta
        candidatos.append((progresso.instante_atingimento, "atingida", EstadoMeta.ATINGIDA, {"motivo": "mantida_com_pendencia_indeterminada"}))

    instantes_invalidacao = [e.horario_evidencia for e in historia if e.tipo is TipoEvento.INVALIDADA]
    if invalidacao is Tri.VERDADEIRO:
        visto = evidencia_da_condicao(r_inv) or agora
        if visto >= ativacao.ativada_em:
            instantes_invalidacao.append(visto)
    if instantes_invalidacao:  # uma invalidação já observada é fato histórico: não some se o preço voltar
        candidatos.append((min(instantes_invalidacao), "invalidada", EstadoMeta.INVALIDADA, {"motivo": "condicao_de_invalidacao"}))

    aguardando = False
    if agora > prazo:
        aguardando = progresso.aguardando_evidencia
        if aguardando and agora <= prazo + carencia:
            pass  # carência: espera evidência, sem novas entradas
        elif aguardando:
            candidatos.append((prazo + carencia, "expirada", EstadoMeta.EXPIRADA, {"motivo": MotivoAvaliacao.PRAZO_SEM_EVIDENCIA.value}))
        else:
            candidatos.append((prazo, "expirada", EstadoMeta.EXPIRADA, {"motivo": MotivoAvaliacao.PRAZO_ENCERRADO.value}))
    progresso = progresso.model_copy(update={"aguardando_evidencia": aguardando or (agora <= prazo and progresso.aguardando_evidencia)})

    ordem = {nome: i for i, nome in enumerate(meta.politicas.ordem_empate)}
    alvo_estado, info = EstadoMeta.ATIVA, {}
    momento_estado = None
    if candidatos:
        momento_estado, _, alvo_estado, info = min(candidatos, key=lambda c: (c[0], ordem[c[1]]))

    # 4) eventos: a diferença entre o estado registrado e o que a evidência mostra
    if estado_antes is EstadoMeta.CANCELADA:
        alvo_estado = EstadoMeta.CANCELADA  # ato humano: o avaliador não o recalcula
    elif estado_antes is EstadoMeta.ATIVA:
        for ev in novos_conc:  # cada compra comprovada vira um fato na história da meta
            if ev.tipo is TipoEventoConciliacao.EXECUCAO_CONCILIADA and ev.delta_progresso > 0 and ev.executada_em is not None:
                emitir(TipoEvento.EXECUCAO_REGISTRADA, ev.executada_em, ev.id,
                       dados={"execucao_id": ev.alvo, "quantidade_liquida": normalizar_decimal(ev.delta_progresso)})
        if alvo_estado is EstadoMeta.ATIVA:
            _emitir_operacionais(meta, historia, novos, emitir, snapshot, agora, bloqueada, bloqueios, entrada, progresso, r_ent)
        else:
            tipo = {EstadoMeta.ATINGIDA: TipoEvento.ATINGIDA, EstadoMeta.EXPIRADA: TipoEvento.EXPIRADA, EstadoMeta.INVALIDADA: TipoEvento.INVALIDADA}[alvo_estado]
            dados = {"quantidade_comprovada": normalizar_decimal(progresso.quantidade_comprovada), "evidencia_em": formatar_instante(momento_estado)}
            emitir(tipo, momento_estado, f"{tipo.value}|{sequencia_estado}|{formatar_instante(momento_estado)}",
                   motivo=str(info.get("motivo")), dados=dados)
    elif estado_antes in RECONCILIAVEIS and alvo_estado is not estado_antes:
        emitir(TipoEvento.RECONCILIADA, agora, f"reconciliada|{sequencia_estado}|{alvo_estado.value}", autor=AUTOR_SISTEMA,
               motivo=_motivo_reconciliacao(estado_antes, alvo_estado, progresso),
               dados={"estado_anterior": estado_antes.value, "estado_resultante": alvo_estado.value,
                      "quantidade_comprovada": normalizar_decimal(progresso.quantidade_comprovada),
                      "quantidade_alvo": normalizar_decimal(progresso.quantidade_alvo)})

    estado_final = estado_de([*historia, *novos], meta.id)

    # 5) registro da avaliação (reproduzível)
    entradas = hash_canonico({
        "contrato": ativacao.contrato_hash, "ativada_em": ativacao.ativada_em, "eventos": sorted(e.id for e in historia),
        "razao": sorted(e.id for e in razao), "relatorio": relatorio.hash_saida, "snapshot": snapshot.id, "agora": agora,
    }, DOMINIO_ENTRADAS)
    avaliacao = Avaliacao(
        id="av-" + hash_canonico({"meta": meta.id, "agora": agora, "entradas": entradas}, DOMINIO_ENTRADAS)[:24],
        meta_id=meta.id, avaliada_em=agora, versao_motor=VERSAO_MOTOR, snapshot_id=snapshot.id, hash_entradas=entradas, estado=estado_final,
        bloqueada_por_dados=bloqueada_por_dados([*historia, *novos], meta.id), resultados=tuple(resultados_regras),
    )
    avaliacao = avaliacao.model_copy(update={"hash_saida": hash_canonico(avaliacao, DOMINIO_SAIDA)})
    return ResultadoAvaliacao(avaliacao=avaliacao, estado_anterior=estado_antes, estado=estado_final, progresso=progresso,
                              eventos=tuple(novos), eventos_conciliacao=tuple(novos_conc))


def _motivo_reconciliacao(antes: EstadoMeta, depois: EstadoMeta, progresso) -> str:
    qtd, alvo = normalizar_decimal(progresso.quantidade_comprovada), normalizar_decimal(progresso.quantidade_alvo)
    if depois is EstadoMeta.ATINGIDA:
        return f"evidência tardia comprova o objetivo ({qtd} de {alvo}); o estado anterior ({antes.value}) permanece na história"
    return (f"correção posterior reduziu ou deixou de comprovar o objetivo ({qtd} de {alvo}); "
            f"a conclusão anterior ({antes.value}) permanece na história e o estado foi recalculado")


def _emitir_operacionais(meta, historia, novos, emitir, snapshot, agora, bloqueada, bloqueios, entrada, progresso, r_ent) -> None:
    """Condição operacional (bloqueio por dados) e alerta de entrada. Só em meta ativa, dentro do prazo."""
    antes = bloqueada_por_dados([*historia, *novos], meta.id)
    if bloqueada and not antes:
        emitir(TipoEvento.BLOQUEIO_INICIADO, agora, f"inicio|{snapshot.id}", motivo="dados obrigatórios indisponíveis ou inválidos")
    elif not bloqueada and antes:
        emitir(TipoEvento.BLOQUEIO_ENCERRADO, agora, f"fim|{snapshot.id}")
    pode_entrar = (
        not bloqueada and bloqueios is Tri.VERDADEIRO and entrada is Tri.VERDADEIRO
        and agora <= meta.objetivo.prazo  # a carência não estende o prazo de compras
        and progresso.quantidade_comprovada < progresso.quantidade_alvo
        and progresso.orcamento.resultado is not Tri.FALSO
    )
    if pode_entrar:
        chave = hash_canonico({"meta": meta.id, "regras": sorted(r.condicao_id for r in r_ent), "snapshot": snapshot.id}, DOMINIO_EVENTO)
        emitir(TipoEvento.ALERTA_EMITIDO, agora, chave, idempotencia=chave, dados={"regra": "entrada"})
