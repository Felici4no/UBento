"""Conciliação de execuções internas com registros externos. Função pura: sem relógio, sem I/O.

Regras e resultados em docs/CONCILIACAO.md. Resumo: a correspondência é feita só por identificador estável; preço e
horário nunca criam um elo; o que é incerto vai para revisão; só execução `conciliada` conta no progresso.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal, localcontext
from fractions import Fraction
from typing import Iterable, Sequence

from ..canonico import hash_canonico, json_canonico
from ..esquema import Execucao, LadoExecucao
from ..tipos import formatar_instante, normalizar_decimal
from .modelos import (
    INFORMATIVOS, Cobertura, Confirmacao, CustoPorAtivo, Diferenca, Motivo, Movimentacao, PoliticaConciliacao,
    ProgressoMeta, RefResolvida, RegistroExterno, RelatorioConciliacao, ResultadoExecucao, ResultadoExterno,
    SaldoObservado, StatusConciliacao, StatusRegistroExterno, VinculoManual,
)
from .saldos import conciliar_saldos

DOMINIO_ENTRADAS = "ubento.conciliacao.entradas.v1"
DOMINIO_SAIDA = "ubento.conciliacao.saida.v1"
MAX_CANDIDATOS = 5

Chave = tuple[str, str]  # (fonte_id, id_externo)


def _fr(valor: Decimal) -> Fraction:
    return Fraction(valor)


def _txt(valor: Fraction | None) -> str | None:
    """Fração → texto decimal canônico (exato quando a fração é decimal; senão 28 dígitos)."""
    if valor is None:
        return None
    with localcontext() as ctx:
        ctx.prec = 28
        return normalizar_decimal(Decimal(valor.numerator) / Decimal(valor.denominator))


@dataclass
class _Ref:
    fonte_id: str
    id_externo: str
    alocada: Decimal | None
    manual: bool = False

    @property
    def chave(self) -> Chave:
        return (self.fonte_id, self.id_externo)


@dataclass
class _Contexto:
    politica: PoliticaConciliacao
    agora: datetime
    atual: dict[Chave, RegistroExterno]
    conflitantes: set[Chave]
    corrigidas: set[Chave]
    problemas_de_alocacao: dict[Chave, Motivo] = field(default_factory=dict)
    reivindicadas: set[Chave] = field(default_factory=set)


# -- preparação dos dados ----------------------------------------------------------------------------------


def _unicas(execucoes: Iterable[Execucao]) -> tuple[dict[str, Execucao], set[str], set[str]]:
    """(execuções por id, ids com duplicata idêntica, ids conflitantes). Conflitantes ficam fora do cálculo."""
    grupos: dict[str, list[Execucao]] = defaultdict(list)
    for e in execucoes:
        grupos[e.id].append(e)
    unicas, duplicadas, conflitantes = {}, set(), set()
    for id_, itens in grupos.items():
        distintos = {json_canonico(i): i for i in itens}
        ordenados = [distintos[k] for k in sorted(distintos)]
        unicas[id_] = ordenados[0]
        if len(distintos) > 1:
            conflitantes.add(id_)
        elif len(itens) > 1:
            duplicadas.add(id_)
    return unicas, duplicadas, conflitantes


def _historia_externa(externos: Iterable[RegistroExterno]) -> tuple[dict[Chave, RegistroExterno], set[Chave], set[Chave]]:
    grupos: dict[Chave, list[RegistroExterno]] = defaultdict(list)
    for r in externos:
        grupos[r.chave].append(r)
    atual, conflitantes, corrigidas = {}, set(), set()
    for chave, regs in grupos.items():
        maior = max(r.versao for r in regs)
        topo = {json_canonico(r): r for r in regs if r.versao == maior}
        ordenados = [topo[k] for k in sorted(topo)]
        atual[chave] = ordenados[0]
        if len(topo) > 1:
            conflitantes.add(chave)
        if any(r.versao < maior for r in regs):
            corrigidas.add(chave)
    return atual, conflitantes, corrigidas


def _referencias(execucao: Execucao, vinculos: Sequence[VinculoManual]) -> list[_Ref]:
    refs = {(r.fonte_id, r.id_externo): _Ref(r.fonte_id, r.id_externo, r.quantidade_bruta_alocada) for r in execucao.referencias_externas}
    for v in sorted((v for v in vinculos if v.execucao_id == execucao.id), key=lambda v: (v.em, v.fonte_id, v.id_externo)):
        refs.setdefault((v.fonte_id, v.id_externo), _Ref(v.fonte_id, v.id_externo, v.quantidade_bruta_alocada, manual=True))
    return [refs[k] for k in sorted(refs)]


def _alocacoes(unicas: dict[str, Execucao], ids_validos: set[str], refs_por_exec: dict[str, list[_Ref]], ctx: _Contexto) -> None:
    """Detecta registros externos usados além da sua quantidade (inclusive por metas diferentes)."""
    reivindicacoes: dict[Chave, list[tuple[Execucao, _Ref]]] = defaultdict(list)
    for id_ in sorted(unicas):
        for ref in refs_por_exec[id_]:
            ctx.reivindicadas.add(ref.chave)  # mesmo sob revisão, o registro "tem dono": não é órfão
            if id_ in ids_validos and ref.chave in ctx.atual:
                reivindicacoes[ref.chave].append((unicas[id_], ref))
    for chave, itens in reivindicacoes.items():
        registro = ctx.atual[chave]
        total = sum((_fr(r.alocada) if r.alocada is not None else _fr(registro.quantidade) for _, r in itens), Fraction(0))
        if total <= _fr(registro.quantidade) + _fr(ctx.politica.tolerancia_de(registro.ativo_id)):
            continue
        metas = {e.meta_id for e, _ in itens}
        integral = any(r.alocada is None for _, r in itens)
        if len(itens) > 1 and len(metas) > 1:
            ctx.problemas_de_alocacao[chave] = Motivo.REGISTRO_EXTERNO_EM_METAS_DIFERENTES
        elif len(itens) > 1 and integral:
            ctx.problemas_de_alocacao[chave] = Motivo.REGISTRO_EXTERNO_EM_VARIAS_EXECUCOES
        else:
            ctx.problemas_de_alocacao[chave] = Motivo.ALOCACAO_EXCEDE_REGISTRO_EXTERNO


# -- comparação ----------------------------------------------------------------------------------------------------


def _comparar(execucao: Execucao, pares: list[tuple[_Ref, RegistroExterno]], politica: PoliticaConciliacao) -> tuple[list[Diferenca], list[Motivo]]:
    diferencas: list[Diferenca] = []
    motivos: list[Motivo] = []

    def registrar(motivo: Motivo, campo: str, interno: Fraction | str | None, externo: Fraction | str | None) -> None:
        if motivo not in motivos:
            motivos.append(motivo)
        diferencas.append(Diferenca(
            campo=campo,
            interno=interno if isinstance(interno, str) or interno is None else _txt(interno),
            externo=externo if isinstance(externo, str) or externo is None else _txt(externo),
        ))

    for _, reg in pares:
        if reg.ativo_id != execucao.ativo_id:
            registrar(Motivo.ATIVO_DIFERENTE, "ativo_id", execucao.ativo_id, reg.ativo_id)
        if reg.lado is not execucao.lado:
            registrar(Motivo.LADO_DIFERENTE, "lado", execucao.lado.value, reg.lado.value)
        if execucao.moeda_cotacao_id is not None and reg.moeda_cotacao_id != execucao.moeda_cotacao_id:
            registrar(Motivo.MOEDA_COTACAO_DIFERENTE, "moeda_cotacao_id", execucao.moeda_cotacao_id, reg.moeda_cotacao_id)
        desvio = abs((reg.executado_em - execucao.executada_em).total_seconds())
        if desvio > politica.tolerancia_horario_segundos:
            registrar(Motivo.HORARIO_FORA_DA_TOLERANCIA, "executada_em", formatar_instante(execucao.executada_em), formatar_instante(reg.executado_em))

    moeda = execucao.moeda_cotacao_id or (pares[0][1].moeda_cotacao_id if pares else None)
    bruta = Fraction(0)
    preco_ponderado = Fraction(0)
    taxa_ativo = Fraction(0)
    taxa_cotacao = Fraction(0)
    outras: dict[str, Fraction] = defaultdict(Fraction)
    for ref, reg in pares:
        alocada = _fr(ref.alocada) if ref.alocada is not None else _fr(reg.quantidade)
        proporcao = alocada / _fr(reg.quantidade)
        bruta += alocada
        preco_ponderado += alocada * _fr(reg.preco)
        for taxa in reg.taxas:
            parte = _fr(taxa.valor) * proporcao
            if taxa.ativo_id == execucao.ativo_id:
                taxa_ativo += parte  # reduz a quantidade recebida
            elif taxa.ativo_id == moeda:
                taxa_cotacao += parte  # custo na moeda de cotação
            else:
                outras[taxa.ativo_id] += parte  # custo em outro ativo; nunca converte nem subtrai unidades

    tol_ativo = _fr(politica.tolerancia_de(execucao.ativo_id))
    if abs(bruta - _fr(execucao.quantidade_bruta)) > tol_ativo:
        registrar(Motivo.QUANTIDADE_BRUTA_DIFERENTE, "quantidade_bruta", _fr(execucao.quantidade_bruta), bruta)
    if abs(taxa_ativo - _fr(execucao.taxa_no_ativo)) > tol_ativo:
        registrar(Motivo.TAXA_NO_ATIVO_DIFERENTE, "taxa_no_ativo", _fr(execucao.taxa_no_ativo), taxa_ativo)
    liquida = bruta - taxa_ativo
    if abs(liquida - _fr(execucao.quantidade_liquida)) > 2 * tol_ativo:
        registrar(Motivo.QUANTIDADE_LIQUIDA_DIFERENTE, "quantidade_liquida", _fr(execucao.quantidade_liquida), liquida)

    if bruta > 0:
        vwap = preco_ponderado / bruta
        interno = _fr(execucao.preco_executado)
        if abs(vwap - interno) > _fr(politica.tolerancia_preco_relativa) * interno:
            registrar(Motivo.PRECO_DIFERENTE, "preco_executado", interno, vwap)

    tol_moeda = _fr(politica.tolerancia_de(moeda)) if moeda else Fraction(0)
    if abs(taxa_cotacao - _fr(execucao.taxa_na_cotacao)) > tol_moeda:
        registrar(Motivo.TAXA_NA_COTACAO_DIFERENTE, "taxa_na_cotacao", _fr(execucao.taxa_na_cotacao), taxa_cotacao)

    internas = {t.ativo_id: _fr(t.valor) for t in execucao.taxas_outros_ativos}
    for ativo in sorted(set(internas) | set(outras)):
        interno, externo = internas.get(ativo), outras.get(ativo)
        if interno is None:
            registrar(Motivo.TAXA_OUTRO_ATIVO_NAO_REGISTRADA, f"taxa:{ativo}", None, externo)
        elif abs(interno - (externo or Fraction(0))) > _fr(politica.tolerancia_de(ativo)):
            registrar(Motivo.TAXA_OUTRO_ATIVO_DIFERENTE, f"taxa:{ativo}", interno, externo or Fraction(0))
    return diferencas, motivos


def _candidatos(execucao: Execucao, atual: dict[Chave, RegistroExterno], reivindicadas: set[Chave], politica: PoliticaConciliacao) -> tuple[RefResolvida, ...]:
    """Sugestões para uma pessoa. NUNCA viram elo: a correspondência exige identificador."""
    achados = []
    tol = _fr(politica.tolerancia_de(execucao.ativo_id))
    for chave, reg in atual.items():
        if chave in reivindicadas or reg.status is StatusRegistroExterno.CANCELADO:
            continue
        if reg.ativo_id != execucao.ativo_id or reg.lado is not execucao.lado:
            continue
        desvio = abs((reg.executado_em - execucao.executada_em).total_seconds())
        if desvio > politica.janela_candidatos_segundos:
            continue
        if abs(_fr(reg.quantidade) - _fr(execucao.quantidade_bruta)) > tol:
            continue
        achados.append((desvio, chave, reg.versao))
    return tuple(RefResolvida(fonte_id=c[0], id_externo=c[1], versao=v) for _, c, v in sorted(achados)[:MAX_CANDIDATOS])


# -- avaliação de uma execução --------------------------------------------------------------------------------------------


def _avaliar(execucao: Execucao, refs: list[_Ref], ctx: _Contexto, duplicada: bool, conflitante: bool) -> ResultadoExecucao:
    assinatura = 1 if execucao.lado is LadoExecucao.COMPRA else -1
    declarado = Decimal(assinatura) * execucao.quantidade_liquida

    def resultado(status: StatusConciliacao, motivos: Iterable[Motivo], *, externos=(), candidatos=(), diferencas=(), efeito=Decimal(0), declarado_=None):
        ordenados = tuple(dict.fromkeys(motivos))
        extras = []
        if duplicada:
            extras.append(Motivo.DUPLICATA_IDENTICA)
        extras += [Motivo.CORRIGIDO_EXTERNAMENTE] if any((r.fonte_id, r.id_externo) in ctx.corrigidas for r in externos) else []
        return ResultadoExecucao(
            execucao_id=execucao.id, meta_id=execucao.meta_id, ativo_id=execucao.ativo_id, lado=execucao.lado,
            executada_em=execucao.executada_em, status=status, motivos=ordenados + tuple(m for m in extras if m not in ordenados),
            externos=tuple(externos), candidatos=tuple(candidatos), diferencas=tuple(diferencas), efeito_no_progresso=efeito,
            declarado=declarado if declarado_ is None else declarado_,
        )

    if conflitante:
        return resultado(StatusConciliacao.REVISAO, [Motivo.ID_INTERNO_DUPLICADO_CONTEUDO_DIFERENTE], declarado_=Decimal(0))
    if not refs:
        cands = _candidatos(execucao, ctx.atual, ctx.reivindicadas, ctx.politica)
        return resultado(StatusConciliacao.REVISAO, [Motivo.SEM_IDENTIFICADOR_EXTERNO], candidatos=cands)

    resolvidas = [(r, ctx.atual[r.chave]) for r in refs if r.chave in ctx.atual]
    faltando = [r for r in refs if r.chave not in ctx.atual]
    externos = [RefResolvida(fonte_id=r.fonte_id, id_externo=r.id_externo, versao=g.versao) for r, g in resolvidas]

    revisao: list[Motivo] = []
    for r, _ in resolvidas:
        if r.chave in ctx.conflitantes:
            revisao.append(Motivo.VERSAO_EXTERNA_CONFLITANTE)
        if r.chave in ctx.problemas_de_alocacao:
            revisao.append(ctx.problemas_de_alocacao[r.chave])
    if revisao:
        return resultado(StatusConciliacao.REVISAO, revisao, externos=externos)

    if faltando:
        idade = (ctx.agora - execucao.confirmada_em).total_seconds()
        if idade <= ctx.politica.janela_atraso_segundos:
            return resultado(StatusConciliacao.PENDENTE, [Motivo.AGUARDANDO_REGISTRO_EXTERNO], externos=externos)
        return resultado(StatusConciliacao.SEM_REGISTRO_EXTERNO, [Motivo.REGISTRO_EXTERNO_NAO_ENCONTRADO], externos=externos)
    if any(g.status is StatusRegistroExterno.PENDENTE for _, g in resolvidas):
        return resultado(StatusConciliacao.PENDENTE, [Motivo.REGISTRO_EXTERNO_PENDENTE], externos=externos)
    if any(g.status is StatusRegistroExterno.CANCELADO for _, g in resolvidas):
        return resultado(StatusConciliacao.DIVERGENTE, [Motivo.CANCELADO_EXTERNAMENTE], externos=externos)

    diferencas, motivos = _comparar(execucao, resolvidas, ctx.politica)
    if motivos:
        return resultado(StatusConciliacao.DIVERGENTE, motivos, externos=externos, diferencas=diferencas)
    return resultado(StatusConciliacao.CONCILIADA, [], externos=externos, efeito=declarado)


def _revisar_estornos(resultados: dict[str, ResultadoExecucao], unicas: dict[str, Execucao], refs_por_exec: dict[str, list[_Ref]], ctx: _Contexto) -> None:
    """Um estorno só vale se a original existir, for da mesma meta, estiver conciliada e não for excedida."""
    acumulado: dict[str, Fraction] = defaultdict(Fraction)
    estornos = sorted((e for e in unicas.values() if e.lado is LadoExecucao.ESTORNO_COMPRA and resultados[e.id].status is StatusConciliacao.CONCILIADA),
                      key=lambda e: (e.executada_em, e.id))
    for e in estornos:
        original = unicas.get(e.estorna_execucao_id or "")
        motivo: Motivo | None = None
        if original is None or original.lado is not LadoExecucao.COMPRA:
            motivo = Motivo.ESTORNO_SEM_ORIGINAL
        elif original.meta_id != e.meta_id:
            motivo = Motivo.ESTORNO_DE_OUTRA_META
        elif resultados[original.id].status is not StatusConciliacao.CONCILIADA:
            motivo = Motivo.ESTORNO_DE_ORIGINAL_NAO_CONCILIADA
        else:
            alvo = {r.id_externo for r in refs_por_exec[original.id]}
            apontados = {ctx.atual[r.chave].estorna_id_externo for r in refs_por_exec[e.id] if r.chave in ctx.atual}
            if not apontados <= alvo:
                motivo = Motivo.ESTORNO_EXTERNO_APONTA_PARA_OUTRA_EXECUCAO
            elif acumulado[original.id] + _fr(e.quantidade_liquida) > _fr(original.quantidade_liquida):
                motivo = Motivo.ESTORNO_EXCEDE_ORIGINAL
        if motivo is None:
            acumulado[original.id] += _fr(e.quantidade_liquida)
            continue
        antigo = resultados[e.id]
        resultados[e.id] = antigo.model_copy(update={
            "status": StatusConciliacao.REVISAO, "motivos": tuple(dict.fromkeys((motivo, *antigo.motivos))), "efeito_no_progresso": Decimal(0),
        })


# -- progresso -----------------------------------------------------------------------------------------------------------------


def _progresso(resultados: Sequence[ResultadoExecucao], unicas: dict[str, Execucao], orfaos: Sequence[ResultadoExterno], politica: PoliticaConciliacao) -> tuple[ProgressoMeta, ...]:
    por_meta: dict[str, list[ResultadoExecucao]] = defaultdict(list)
    for r in resultados:
        por_meta[r.meta_id].append(r)
    saida = []
    for meta_id in sorted(por_meta):
        itens = sorted(por_meta[meta_id], key=lambda r: r.execucao_id)
        ativos = {r.ativo_id for r in itens}
        ativo = next(iter(ativos)) if len(ativos) == 1 else None
        comprovado = sum((r.efeito_no_progresso for r in itens), Decimal(0))
        declarado = sum((r.declarado for r in itens), Decimal(0))
        por_status: dict[str, int] = defaultdict(int)
        taxas_ativo = Fraction(0)
        custos: dict[str, Fraction] = defaultdict(Fraction)
        for r in itens:
            por_status[r.status.value] += 1
            if r.status is StatusConciliacao.CONCILIADA:
                e = unicas[r.execucao_id]
                taxas_ativo += _fr(e.taxa_no_ativo) * (1 if e.lado is LadoExecucao.COMPRA else -1)
                if e.moeda_cotacao_id:
                    custos[e.moeda_cotacao_id] += _fr(e.taxa_na_cotacao) + _fr(e.custo_fixo_real)
                for t in e.taxas_outros_ativos:
                    custos[t.ativo_id] += _fr(t.valor)
        n_orfaos = sum(1 for o in orfaos if ativo is not None and o.ativo_id == ativo and o.lado is LadoExecucao.COMPRA)
        pendencias = [f"{r.execucao_id}: {r.status.value} ({', '.join(m.value for m in r.motivos if m not in INFORMATIVOS)})"
                      for r in itens if r.status is not StatusConciliacao.CONCILIADA]
        if ativo is None:
            pendencias.append("meta com execuções de ativos diferentes")
        if n_orfaos and politica.orfaos_bloqueiam_confirmacao:
            pendencias.append(f"{n_orfaos} registro(s) externo(s) de compra do ativo sem execução interna")
        saida.append(ProgressoMeta(
            meta_id=meta_id, ativo_id=ativo, comprovado=comprovado, declarado=declarado, nao_comprovado=declarado - comprovado,
            por_status=dict(sorted(por_status.items())),
            taxas_no_ativo=Decimal(taxas_ativo.numerator) / Decimal(taxas_ativo.denominator),
            custos=tuple(CustoPorAtivo(ativo_id=a, valor=Decimal(v.numerator) / Decimal(v.denominator)) for a, v in sorted(custos.items())),
            orfaos_do_ativo=n_orfaos,
            confirmacao=Confirmacao.INCOMPLETA if pendencias else Confirmacao.CONFIRMADA, pendencias=tuple(pendencias),
        ))
    return tuple(saida)


# -- API -----------------------------------------------------------------------------------------------------------------------------------


def hash_das_entradas(*, agora, politica, execucoes, externos, movimentacoes, saldos, coberturas, vinculos) -> str:
    def lote(itens):
        return sorted(json_canonico(i) for i in itens)

    return hash_canonico({
        "agora": agora, "politica": politica, "execucoes": lote(execucoes), "externos": lote(externos),
        "movimentacoes": lote(movimentacoes), "saldos": lote(saldos), "coberturas": lote(coberturas), "vinculos": lote(vinculos),
    }, DOMINIO_ENTRADAS)


def conciliar(
    execucoes: Sequence[Execucao],
    externos: Sequence[RegistroExterno],
    *,
    politica: PoliticaConciliacao,
    agora: datetime,
    movimentacoes: Sequence[Movimentacao] = (),
    saldos: Sequence[SaldoObservado] = (),
    coberturas: Sequence[Cobertura] = (),
    vinculos: Sequence[VinculoManual] = (),
) -> RelatorioConciliacao:
    """Concilia o que era conhecido em `agora`. Mesmas entradas e mesmo `agora` → mesmo relatório (mesmo hash)."""
    hash_entradas = hash_das_entradas(agora=agora, politica=politica, execucoes=execucoes, externos=externos,
                                      movimentacoes=movimentacoes, saldos=saldos, coberturas=coberturas, vinculos=vinculos)
    # só existe o que já tinha chegado em `agora`
    execucoes_v = [e for e in execucoes if e.confirmada_em <= agora]
    externos_v = [r for r in externos if r.recebido_em <= agora]
    vinculos_v = [v for v in vinculos if v.em <= agora]

    unicas, duplicadas, conflitantes_int = _unicas(execucoes_v)
    atual, conflitantes_ext, corrigidas = _historia_externa(externos_v)
    ctx = _Contexto(politica=politica, agora=agora, atual=atual, conflitantes=conflitantes_ext, corrigidas=corrigidas)

    refs_por_exec = {id_: _referencias(e, vinculos_v) for id_, e in unicas.items()}
    validos = set(unicas) - conflitantes_int
    _alocacoes(unicas, validos, refs_por_exec, ctx)

    resultados = {
        id_: _avaliar(unicas[id_], refs_por_exec[id_], ctx, id_ in duplicadas, id_ in conflitantes_int)
        for id_ in sorted(unicas)
    }
    _revisar_estornos(resultados, unicas, refs_por_exec, ctx)

    orfaos = tuple(
        ResultadoExterno(fonte_id=c[0], id_externo=c[1], versao=r.versao, ativo_id=r.ativo_id, lado=r.lado, quantidade=r.quantidade, executado_em=r.executado_em)
        for c, r in sorted(atual.items())
        if c not in ctx.reivindicadas and r.status is not StatusRegistroExterno.CANCELADO
    )
    lista = tuple(resultados[i] for i in sorted(resultados))
    progresso = _progresso(lista, unicas, orfaos, politica)
    saldos_resultado = conciliar_saldos(
        [s for s in saldos if s.recebido_em <= agora], [m for m in movimentacoes if m.recebido_em <= agora],
        coberturas, atual, politica,
    )
    confirmada = all(p.confirmacao is Confirmacao.CONFIRMADA for p in progresso) and not (politica.orfaos_bloqueiam_confirmacao and orfaos)
    relatorio = RelatorioConciliacao(
        agora=agora, hash_entradas=hash_entradas, execucoes=lista, orfaos=orfaos, saldos=saldos_resultado, progresso=progresso,
        confirmacao=Confirmacao.CONFIRMADA if confirmada else Confirmacao.INCOMPLETA,
    )
    return relatorio.model_copy(update={"hash_saida": hash_canonico(relatorio, DOMINIO_SAIDA)})
