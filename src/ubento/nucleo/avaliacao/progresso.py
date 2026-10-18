"""Do relatório de conciliação ao progresso de UMA meta.

Aqui moram os critérios que separam quantidade comprovada, completude, custos verificados e elegibilidade.
Tudo é função pura de (contrato, ativação, relatório, efeitos do razão, agora).
"""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from fractions import Fraction
from typing import Mapping, Sequence

from ..conciliacao.eventos import EfeitoExecucao
from ..conciliacao.modelos import CustoPorAtivo, FonteAutorizada, Motivo, RelatorioConciliacao, ResultadoExecucao, ResultadoExterno, StatusConciliacao
from ..esquema import Ativacao, LadoExecucao, Meta, OrigemDado
from ..tipos import Tri
from .modelos import (
    Completude, Elegibilidade, LimiteOrcamento, MotivoAvaliacao as M, MotivoEscopo as E, OrfaoAvaliado, Pendencia, ProgressoAvaliado,
)
from ..regras import todos


def _dec(valor: Fraction) -> Decimal:
    return Decimal(valor.numerator) / Decimal(valor.denominator)


def _fr(valor: Decimal) -> Fraction:
    return Fraction(valor)


# -- escopo dos registros externos sem dono ---------------------------------------------------------------------------------------------


# Campos do contrato que nada avalia ainda. O limite de exposição é obrigatório quando menor que 1 (1 = sem limite): configurado e não
# implementado, ele impede a meta de se declarar cumprida em vez de ser ignorado em silêncio. Os demais são só informativos.
CAMPOS_NAO_AVALIADOS = (
    "recursos.exposicao_maxima", "recursos.saldo_reservado", "custos.custo_fixo", "custos.taxa_proporcional", "custos.tratamento_taxa",
)


def limites_nao_avaliados(meta: Meta) -> tuple[str, ...]:
    return ("recursos.exposicao_maxima",) if meta.recursos.exposicao_maxima < 1 else ()


def avaliar_escopo_orfao(orfao: ResultadoExterno, meta: Meta, ativacao: Ativacao, registros_da_meta: set[tuple[str, str]],
                         origens: frozenset[OrigemDado], autorizadas: Sequence[FonteAutorizada] = ()) -> OrfaoAvaliado:
    """Um registro externo sem execução interna só bloqueia a meta que ele PODE afetar.

    Critérios, nesta ordem (o primeiro que excluir encerra a análise; documentados em docs/AVALIACAO_META.md §3):
      1. ativo         igual ao do objetivo;
      2. mercado       igual ao do contrato;
      3. moeda         de cotação igual à do objetivo;
      4. origem        entre as origens dos dados da meta (dado simulado não bloqueia meta com dado observado);
      5. conta         diferente da conta do contrato exclui; conta desconhecida em qualquer lado NÃO exclui (conservador);
      6. lado/vínculo  estorno só importa se aponta para um registro que a meta usa; compra segue adiante;
      7. período       compra só importa se executada entre a ativação e o prazo.
    """
    chave = (orfao.fonte_id, orfao.id_externo)

    def veredito(relevante: bool, *motivos: E) -> OrfaoAvaliado:
        return OrfaoAvaliado(fonte_id=chave[0], id_externo=chave[1], relevante=relevante, motivos=tuple(motivos))

    o = meta.objetivo
    if orfao.ativo_id != o.ativo_id:
        return veredito(False, E.ATIVO_DIFERENTE)
    if orfao.mercado_id != meta.mercado.mercado_id:
        return veredito(False, E.MERCADO_DIFERENTE)
    if orfao.moeda_cotacao_id != o.moeda_cotacao_id:
        return veredito(False, E.MOEDA_COTACAO_DIFERENTE)
    if origens and orfao.origem not in origens:
        return veredito(False, E.ORIGEM_DIFERENTE)
    conta_meta, conta_orfao = meta.mercado.conta_id, orfao.conta_id
    if conta_meta is not None and conta_orfao is not None and conta_meta != conta_orfao:
        return veredito(False, E.CONTA_DIFERENTE)
    indeterminada = (E.CONTA_INDETERMINADA,) if (conta_meta is None or conta_orfao is None) else ()
    definidas = {a.fonte_id for a in autorizadas if conta_meta is not None and a.conta_id == conta_meta and a.mercado_id == meta.mercado.mercado_id}
    if definidas and orfao.fonte_id not in definidas:  # fonte alternativa, só para comparação: não bloqueia a meta
        return veredito(False, E.FONTE_NAO_AUTORIZADA)

    if orfao.lado is LadoExecucao.ESTORNO_COMPRA:
        if orfao.estorna_id_externo is not None and (orfao.fonte_id, orfao.estorna_id_externo) in registros_da_meta:
            return veredito(True, E.ESTORNO_DE_REGISTRO_DA_META, *indeterminada)
        return veredito(False, E.ESTORNO_DE_OUTRA_COMPRA)
    if not (ativacao.ativada_em <= orfao.executado_em <= o.prazo):
        return veredito(False, E.FORA_DO_PERIODO)
    return veredito(True, E.COMPRA_POSSIVELMENTE_DA_META, *indeterminada)


# -- análise ------------------------------------------------------------------------------------------------------------------------------


def _na_janela(efeito: EfeitoExecucao, ativacao: Ativacao, prazo: datetime) -> bool:
    return efeito.executada_em is not None and ativacao.ativada_em <= efeito.executada_em <= prazo


def analisar_progresso(
    meta: Meta,
    ativacao: Ativacao,
    relatorio: RelatorioConciliacao,
    efeitos: Mapping[str, EfeitoExecucao],
    agora: datetime,
) -> ProgressoAvaliado:
    prazo = meta.objetivo.prazo
    alvo = meta.objetivo.quantidade_alvo
    resultados: dict[str, ResultadoExecucao] = {r.execucao_id: r for r in relatorio.execucoes if r.meta_id == meta.id}
    origens = frozenset(r.origem for r in resultados.values())

    # -- quantidade comprovada, dentro da janela da meta (instante EFETIVO da execução, não o da evidência)
    contadas: list[tuple[datetime, str, Fraction]] = []
    fora = Fraction(0)
    for id_, ef in efeitos.items():
        if ef.efeito == 0:
            continue
        if ef.lado is LadoExecucao.ESTORNO_COMPRA:
            original = efeitos.get(ef.estorna_execucao_id or "")
            conta = original is None or _na_janela(original, ativacao, prazo)  # estorno desfaz uma compra: segue a compra
        else:
            conta = _na_janela(ef, ativacao, prazo)
        if conta and ef.executada_em is not None:
            contadas.append((ef.executada_em, id_, _fr(ef.efeito)))
        else:
            fora += _fr(ef.efeito)
    contadas.sort()
    comprovada = sum((q for _, _, q in contadas), Fraction(0))
    preservada = sum((_fr(ef.efeito) for ef in efeitos.values() if ef.preservado and ef.efeito != 0), Fraction(0))

    # instante em que a quantidade passou a valer de forma SUSTENTADA (a última vez que cruzou o alvo para cima)
    acumulado, cruzou = Fraction(0), None
    for momento, _, qtd in contadas:
        antes = acumulado
        acumulado += qtd
        if antes < _fr(alvo) <= acumulado:
            cruzou = momento
        elif acumulado < _fr(alvo):
            cruzou = None
    instante_atingimento = cruzou if comprovada >= _fr(alvo) else None

    # -- pendências (completude) e escopo dos órfãos
    registros_da_meta = {(x.fonte_id, x.id_externo) for r in resultados.values() for x in r.externos}
    orfaos = [avaliar_escopo_orfao(o, meta, ativacao, registros_da_meta, origens, relatorio.fontes_autorizadas) for o in relatorio.orfaos]
    por_chave: dict[tuple[str, str], ResultadoExterno] = {(o.fonte_id, o.id_externo): o for o in relatorio.orfaos}
    pendencias: list[Pendencia] = []
    pendente_qtd = Fraction(0)

    for id_ in sorted(set(resultados) | set(efeitos)):
        r, ef = resultados.get(id_), efeitos.get(id_)
        if r is not None and r.status is StatusConciliacao.CONCILIADA:
            continue
        status = r.status.value if r else "somente_no_razao"
        motivos = tuple(m.value for m in r.motivos) if r else ()
        if r is None:
            pendencias.append(Pendencia(referencia=id_, origem="execucao", status=status, motivos=motivos,
                                        motivo_avaliacao=M.EXECUCAO_SEM_REGISTRO_INTERNO))
        elif ef is not None and ef.preservado:  # a prova anterior vale; faltou só reverificar (não é uma nova redução)
            pendencias.append(Pendencia(referencia=id_, origem="execucao", status=status, motivos=motivos,
                                        motivo_avaliacao=M.EVIDENCIA_PRESERVADA_SEM_REVERIFICACAO))
        elif r.lado is LadoExecucao.ESTORNO_COMPRA:  # estorno ainda sem prova: pode reduzir o que já está comprovado
            pendencias.append(Pendencia(referencia=id_, origem="execucao", status=status, motivos=motivos,
                                        pode_reduzir_progresso=True, motivo_avaliacao=M.ESTORNO_NAO_CONCILIADO))
        elif r.status in (StatusConciliacao.DIVERGENTE, StatusConciliacao.REVISAO, StatusConciliacao.SEM_REGISTRO_EXTERNO):
            contradita = ef is not None and ef.anterior != 0 and ef.efeito == 0  # só se HAVIA prova e ela foi contraditada
            pendencias.append(Pendencia(referencia=id_, origem="execucao", status=status, motivos=motivos,
                                        motivo_avaliacao=M.PROVA_ANTERIOR_CONTRADITA if contradita else M.COMPRA_NAO_CONCILIADA))
        else:  # pendente / não verificável, sem prova anterior
            pendencias.append(Pendencia(referencia=id_, origem="execucao", status=status, motivos=motivos, motivo_avaliacao=M.COMPRA_NAO_CONCILIADA))
            if r.executada_em <= prazo and r.executada_em >= ativacao.ativada_em and Motivo.FONTE_NAO_AUTORIZADA not in r.motivos:
                pendente_qtd += _fr(r.declarado)  # fonte alternativa nunca é "evidência que ainda pode chegar"

    qtd_orfaos = Fraction(0)
    for ov in orfaos:
        if not ov.relevante:
            continue
        o = por_chave[(ov.fonte_id, ov.id_externo)]
        estorno = o.lado is LadoExecucao.ESTORNO_COMPRA
        pendencias.append(Pendencia(
            referencia=ov.id_externo, origem="registro_externo", status="sem_execucao_interna", motivos=tuple(m.value for m in ov.motivos),
            pode_reduzir_progresso=estorno,
            motivo_avaliacao=M.ESTORNO_POSSIVEL_NAO_VINCULADO if estorno else M.COMPRA_POSSIVEL_NAO_VINCULADA,
        ))
        if not estorno:
            qtd_orfaos += _fr(o.quantidade)

    # -- orçamento: limite obrigatório com pior caso explícito
    slice_ = next((p for p in relatorio.progresso if p.meta_id == meta.id), None)
    custos: tuple[CustoPorAtivo, ...] = slice_.custos if slice_ else ()
    orcamento = _orcamento(meta, resultados, efeitos, [por_chave[(o.fonte_id, o.id_externo)] for o in orfaos if o.relevante], custos)

    # -- elegibilidade: três verificações independentes, combinadas com `todos`
    quantidade_ok = Tri.VERDADEIRO if comprovada >= _fr(alvo) else Tri.FALSO
    reduz = any(p.pode_reduzir_progresso for p in pendencias)
    limites = limites_nao_avaliados(meta)
    verificacoes = [quantidade_ok, Tri.INDETERMINADO if reduz else Tri.VERDADEIRO, orcamento.resultado, Tri.INDETERMINADO if limites else Tri.VERDADEIRO]
    motivos_el: list[M] = []
    if quantidade_ok is Tri.FALSO:
        motivos_el.append(M.QUANTIDADE_INSUFICIENTE)
    if reduz:
        motivos_el.append(M.PENDENCIA_PODE_REDUZIR_PROGRESSO)
    if orcamento.resultado is Tri.FALSO:
        motivos_el.append(M.ORCAMENTO_EXCEDIDO)
    elif orcamento.resultado is Tri.INDETERMINADO:
        motivos_el.append(M.ORCAMENTO_INDETERMINADO)
    if limites:
        motivos_el.append(M.LIMITE_NAO_AVALIADO)
    elegibilidade = Elegibilidade(resultado=todos(verificacoes), motivos=tuple(motivos_el))

    # -- ainda dá para comprovar? (decide se a carência faz sentido)
    potencial = comprovada + pendente_qtd + qtd_orfaos
    aguardando = (comprovada < _fr(alvo) <= potencial) or elegibilidade.resultado is Tri.INDETERMINADO
    carencia = meta.politicas.carencia_dados_segundos
    em_carencia = prazo < agora and (agora - prazo).total_seconds() <= carencia

    return ProgressoAvaliado(
        quantidade_alvo=alvo, quantidade_comprovada=_dec(comprovada), quantidade_fora_da_janela=_dec(fora), quantidade_preservada=_dec(preservada),
        quantidade_pendente=_dec(pendente_qtd), instante_atingimento=instante_atingimento,
        completude=Completude(completa=not pendencias, pendencias=tuple(pendencias)), custos=custos, orcamento=orcamento,
        elegibilidade=elegibilidade, orfaos=tuple(orfaos), aguardando_evidencia=aguardando, em_carencia=em_carencia,
        limites_nao_avaliados=limites, campos_nao_avaliados=CAMPOS_NAO_AVALIADOS,
    )


def _orcamento(meta: Meta, resultados: Mapping[str, ResultadoExecucao], efeitos: Mapping[str, EfeitoExecucao],
               orfaos_relevantes: Sequence[ResultadoExterno], custos: Sequence[CustoPorAtivo] = ()) -> LimiteOrcamento:
    """O orçamento cobre o CUSTO TOTAL: desembolso na moeda de cotação (bruta × preço), taxas na moeda de cotação e o custo fixo como pior caso.
    Gasto mínimo = só o comprovado; máximo = pior caso. O limite só é verdadeiro se o máximo cabe E nada do custo ficou sem como medir:
    taxa em terceiro ativo não é convertida (não há cotação confiável), então, havendo uma, o orçamento nunca é declarado satisfeito
    (indeterminado), salvo se o gasto já conhecido bastar para demonstrar o estouro (falso)."""
    moeda = meta.recursos.moeda_orcamento_id
    orcamento = meta.recursos.orcamento
    minimo, maximo = Fraction(0), Fraction(0)
    motivos: list[M] = []

    for id_ in sorted(set(resultados) | set(efeitos)):
        r, ef = resultados.get(id_), efeitos.get(id_)
        comprovado = _fr(ef.gasto_comprovado) if ef else Fraction(0)  # vale o razão: preserva prova anterior
        declarado_nao = _fr(r.gasto_nao_comprovado) if r else Fraction(0)
        if r is not None and r.status is StatusConciliacao.CONCILIADA:
            declarado_nao = _fr(r.gasto_nao_comprovado)  # custo fixo
        elif ef is not None and ef.preservado and comprovado != 0:
            declarado_nao = max(Fraction(0), declarado_nao - comprovado)  # o que falta além do que já estava provado
        moeda_exec = (r.moeda_gasto if r else None) or (ef.moeda_gasto if ef else None)
        tem_gasto = comprovado != 0 or declarado_nao != 0
        if tem_gasto and moeda_exec is None:
            motivos.append(M.MOEDA_DO_GASTO_DESCONHECIDA)
            continue
        if tem_gasto and moeda_exec != moeda:
            motivos.append(M.MOEDA_INCOMPATIVEL)
            continue
        minimo += comprovado
        maximo += comprovado + declarado_nao
        if declarado_nao != 0:
            motivos.append(M.CUSTOS_SEM_EVIDENCIA)

    ativo = meta.objetivo.ativo_id
    terceiros = any(c.ativo_id not in (moeda, ativo) and (c.verificado + c.nao_verificado) > 0 for c in custos)
    terceiros = terceiros or any(t.ativo_id not in (moeda, ativo) for o in orfaos_relevantes if o.lado is LadoExecucao.COMPRA for t in o.taxas)
    if terceiros:
        motivos.append(M.TAXA_EM_TERCEIRO_ATIVO_SEM_CONVERSAO)

    for o in orfaos_relevantes:
        if o.lado is not LadoExecucao.COMPRA:
            continue
        if o.moeda_cotacao_id != moeda:
            motivos.append(M.MOEDA_INCOMPATIVEL)
            continue
        pago = _fr(o.quantidade) * _fr(o.preco) + sum((_fr(t.valor) for t in o.taxas if t.ativo_id == moeda), Fraction(0))
        maximo += pago
        motivos.append(M.CUSTOS_SEM_EVIDENCIA)

    if minimo > _fr(orcamento):
        resultado, motivos_finais = Tri.FALSO, [M.ORCAMENTO_EXCEDIDO]
    elif maximo <= _fr(orcamento) and not {M.MOEDA_INCOMPATIVEL, M.MOEDA_DO_GASTO_DESCONHECIDA, M.TAXA_EM_TERCEIRO_ATIVO_SEM_CONVERSAO} & set(motivos):
        resultado, motivos_finais = Tri.VERDADEIRO, []
    else:
        resultado = Tri.INDETERMINADO
        motivos_finais = [M.ORCAMENTO_INDETERMINADO, *dict.fromkeys(motivos)]
    return LimiteOrcamento(moeda_id=moeda, orcamento=orcamento, gasto_minimo=_dec(minimo), gasto_maximo=_dec(maximo),
                           resultado=resultado, motivos=tuple(motivos_finais))
