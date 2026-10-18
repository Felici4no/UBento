"""Conciliação de execuções internas com registros externos. Função pura: sem relógio, sem I/O.

Regras e resultados em docs/CONCILIACAO.md. Resumo: a correspondência é feita só por identificador estável; preço e
horário nunca criam um elo; o que é incerto vai para revisão; só execução `conciliada` conta no progresso.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from decimal import Decimal, localcontext
from fractions import Fraction
from typing import Iterable, Sequence

from ..canonico import hash_canonico, json_canonico
from ..esquema import Execucao, LadoExecucao, Meta
from ..tipos import formatar_instante, normalizar_decimal
from .modelos import (
    INFORMATIVOS, Cobertura, CoberturaExecucoes, Confirmacao, CustoPorAtivo, Diferenca, GastoPorAtivo, Motivo, Movimentacao, PoliticaConciliacao,
    ProgressoMeta, RefResolvida, RegistroExterno, RelatorioConciliacao, ResultadoExecucao, ResultadoExterno,
    RevogacaoVinculo, SaldoObservado, StatusConciliacao, StatusRegistroExterno, VinculoManual,
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


def _dec(valor: Fraction) -> Decimal:
    with localcontext() as ctx:
        ctx.prec = 60
        return Decimal(valor.numerator) / Decimal(valor.denominator)


@dataclass
class _Contexto:
    politica: PoliticaConciliacao
    agora: datetime
    atual: dict[Chave, RegistroExterno]
    conflitantes: set[Chave]
    corrigidas: set[Chave]
    problemas_de_alocacao: dict[Chave, Motivo] = field(default_factory=dict)
    reimportadas: set[Chave] = field(default_factory=set)
    metas: dict[str, Meta] = field(default_factory=dict)
    reivindicadas: set[Chave] = field(default_factory=set)
    coberturas: Sequence[CoberturaExecucoes] = ()


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


_SEM_HORA = datetime(1970, 1, 1, tzinfo=timezone.utc)


def _conteudo(r: RegistroExterno) -> str:
    """O CONTEÚDO da operação, sem o metadado de recebimento: `recebido_em` diz quando chegou, não o que aconteceu, e a ordem das
    taxas não é informação. Identidade = (fonte, id); conteúdo = o resto menos o recebimento; recebimento = `recebido_em`."""
    return json_canonico(r.model_copy(update={"recebido_em": _SEM_HORA, "taxas": tuple(sorted(r.taxas, key=lambda t: t.ativo_id))}))


def _historia_externa(externos: Iterable[RegistroExterno]) -> tuple[dict[Chave, RegistroExterno], set[Chave], set[Chave], set[Chave]]:
    """(registro vigente por chave, chaves conflitantes, chaves corrigidas, chaves reimportadas).

    Na versão mais alta, cópias com o mesmo conteúdo são a MESMA operação reimportada: vale a primeira chegada (menor `recebido_em`) e a
    reimportação só é anotada. Conteúdos diferentes na mesma versão são conflito de verdade."""
    grupos: dict[Chave, list[RegistroExterno]] = defaultdict(list)
    for r in externos:
        grupos[r.chave].append(r)
    atual, conflitantes, corrigidas, reimportadas = {}, set(), set(), set()
    for chave, regs in grupos.items():
        maior = max(r.versao for r in regs)
        por_conteudo: dict[str, list[RegistroExterno]] = defaultdict(list)
        for r in regs:
            if r.versao == maior:
                por_conteudo[_conteudo(r)].append(r)
        primeiras = {c: min(copias, key=lambda r: (r.recebido_em, json_canonico(r))) for c, copias in por_conteudo.items()}
        atual[chave] = primeiras[sorted(primeiras)[0]]
        if len(por_conteudo) > 1:
            conflitantes.add(chave)
        if any(len(copias) > 1 for copias in por_conteudo.values()):
            reimportadas.add(chave)
        if any(r.versao < maior for r in regs):
            corrigidas.add(chave)
    return atual, conflitantes, corrigidas, reimportadas


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
        if reg.origem is not execucao.origem:  # evidência simulada não comprova execução real (nem o inverso)
            registrar(Motivo.ORIGEM_DIFERENTE, "origem", execucao.origem.value, reg.origem.value)
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


def _ausencia_provada(execucao: Execucao, ref: _Ref, ctx: _Contexto) -> bool:
    """A ausência do registro externo só é prova se uma consulta COMPLETA daquele período já tinha sido feita.

    Idade da execução diz se o registro já deveria existir; cobertura diz se a consulta teria visto o registro.
    São coisas diferentes: sem cobertura, a ausência é só "não verificável".
    """
    tol = timedelta(seconds=ctx.politica.tolerancia_horario_segundos)
    minimo = execucao.confirmada_em + timedelta(seconds=ctx.politica.janela_atraso_segundos)
    return any(
        c.fonte_id == ref.fonte_id and c.ativo_id in (None, execucao.ativo_id)
        and c.inicio <= execucao.executada_em - tol and c.fim >= execucao.executada_em + tol and c.consultada_em >= minimo
        for c in ctx.coberturas
    )


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


# -- contexto da meta ------------------------------------------------------------------------------------------------------


def _contexto_da_execucao(e: Execucao, meta: Meta) -> list[Motivo]:
    """Incompatibilidades EXPLÍCITAS da execução com o objetivo da meta (independem de evidência)."""
    motivos = []
    if e.ativo_id != meta.objetivo.ativo_id:
        motivos.append(Motivo.ATIVO_DA_META_DIFERENTE)
    if e.moeda_cotacao_id is not None and e.moeda_cotacao_id != meta.objetivo.moeda_cotacao_id:
        motivos.append(Motivo.MOEDA_DA_META_DIFERENTE)
    return motivos


def _contexto_dos_registros(registros: Iterable[RegistroExterno], meta: Meta) -> tuple[list[Motivo], bool]:
    """(incompatibilidades explícitas, conta indeterminada) dos registros que sustentam a execução, frente à meta.
    Explícita = dado presente dos dois lados e diferente. Indeterminada = a conta falta no registro ou no contrato."""
    explicitas: list[Motivo] = []
    indeterminada = False
    for reg in registros:
        if reg.ativo_id != meta.objetivo.ativo_id:
            explicitas.append(Motivo.ATIVO_DA_META_DIFERENTE)
        if reg.moeda_cotacao_id != meta.objetivo.moeda_cotacao_id:
            explicitas.append(Motivo.MOEDA_DA_META_DIFERENTE)
        if reg.mercado_id != meta.mercado.mercado_id:
            explicitas.append(Motivo.MERCADO_DA_META_DIFERENTE)
        if reg.conta_id is None or meta.mercado.conta_id is None:
            indeterminada = True
        elif reg.conta_id != meta.mercado.conta_id:
            explicitas.append(Motivo.CONTA_DA_META_DIFERENTE)
    return list(dict.fromkeys(explicitas)), indeterminada


def fonte_autorizada(meta: Meta, fonte_id: str, politica: PoliticaConciliacao) -> bool | None:
    """True/False se a política diz se `fonte_id` comprova para o (conta, mercado) da meta; None se não há fonte definida para o contexto."""
    conta = meta.mercado.conta_id
    definidas = [a for a in politica.fontes_autorizadas if conta is not None and a.conta_id == conta and a.mercado_id == meta.mercado.mercado_id]
    if not definidas:
        return None
    return any(a.fonte_id == fonte_id for a in definidas)


# -- avaliação de uma execução --------------------------------------------------------------------------------------------


def _gastos(execucao: Execucao, conciliada: bool) -> tuple[Decimal, Decimal]:
    """(comprovado, não comprovado) na moeda de cotação.

    Conciliada: valor pago e taxa na cotação são comprovados (foram conferidos); o custo fixo NÃO (não há evidência
    externa dele). Não conciliada: nada é comprovado e a compra inteira é um limite superior de gasto.
    """
    nocional = _fr(execucao.quantidade_bruta) * _fr(execucao.preco_executado)
    compra = execucao.lado is LadoExecucao.COMPRA
    taxa, fixo = _fr(execucao.taxa_na_cotacao), _fr(execucao.custo_fixo_real)
    if conciliada:
        return _dec((nocional if compra else -nocional) + taxa), _dec(fixo)
    return Decimal(0), _dec((nocional if compra else Fraction(0)) + taxa + fixo)


def _avaliar(execucao: Execucao, refs: list[_Ref], ctx: _Contexto, duplicada: bool, conflitante: bool) -> ResultadoExecucao:
    assinatura = 1 if execucao.lado is LadoExecucao.COMPRA else -1
    declarado = Decimal(assinatura) * execucao.quantidade_liquida

    def resultado(status: StatusConciliacao, motivos: Iterable[Motivo], *, externos=(), candidatos=(), diferencas=(), efeito=Decimal(0), declarado_=None):
        ordenados = tuple(dict.fromkeys(motivos))
        extras = []
        if duplicada:
            extras.append(Motivo.DUPLICATA_IDENTICA)
        extras += [Motivo.CORRIGIDO_EXTERNAMENTE] if any((r.fonte_id, r.id_externo) in ctx.corrigidas for r in externos) else []
        extras += [Motivo.REGISTRO_EXTERNO_REIMPORTADO] if any((r.fonte_id, r.id_externo) in ctx.reimportadas for r in externos) else []
        comprovado_g, nao_comprovado_g = _gastos(execucao, status is StatusConciliacao.CONCILIADA)
        moeda = execucao.moeda_cotacao_id or next(
            (ctx.atual[(r.fonte_id, r.id_externo)].moeda_cotacao_id for r in externos if (r.fonte_id, r.id_externo) in ctx.atual), None)
        return ResultadoExecucao(
            execucao_id=execucao.id, meta_id=execucao.meta_id, ativo_id=execucao.ativo_id, lado=execucao.lado,
            executada_em=execucao.executada_em, status=status, motivos=ordenados + tuple(m for m in extras if m not in ordenados),
            externos=tuple(externos), candidatos=tuple(candidatos), diferencas=tuple(diferencas), efeito_no_progresso=efeito,
            declarado=declarado if declarado_ is None else declarado_, estorna_execucao_id=execucao.estorna_execucao_id, origem=execucao.origem,
            moeda_gasto=moeda, gasto_comprovado=comprovado_g, gasto_nao_comprovado=nao_comprovado_g,
        )

    if conflitante:
        return resultado(StatusConciliacao.REVISAO, [Motivo.ID_INTERNO_DUPLICADO_CONTEUDO_DIFERENTE], declarado_=Decimal(0))
    meta = ctx.metas.get(execucao.meta_id)
    if meta is not None:
        explicitas = _contexto_da_execucao(execucao, meta)
        if explicitas:  # ativo ou moeda incompatíveis com a meta: não comprova, com ou sem evidência
            return resultado(StatusConciliacao.DIVERGENTE, explicitas)
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

    indeterminada = False
    if meta is not None:
        explicitas, indeterminada = _contexto_dos_registros((g for _, g in resolvidas), meta)
        if explicitas:  # evidência de outra conta, mercado, moeda ou ativo: incompatibilidade explícita nunca comprova
            return resultado(StatusConciliacao.DIVERGENTE, explicitas, externos=externos)
        if meta.mercado.conta_id is None:
            return resultado(StatusConciliacao.NAO_VERIFICAVEL, [Motivo.CONTEXTO_INDETERMINADO], externos=externos)
        permissoes = {fonte_autorizada(meta, r.fonte_id, ctx.politica) for r in refs}
        if None in permissoes:
            return resultado(StatusConciliacao.NAO_VERIFICAVEL, [Motivo.FONTE_AUTORIZADA_NAO_DEFINIDA], externos=externos)
        if False in permissoes:  # fonte alternativa: serve para comparar, não para comprovar
            return resultado(StatusConciliacao.NAO_VERIFICAVEL, [Motivo.FONTE_NAO_AUTORIZADA], externos=externos)

    if faltando:
        idade = (ctx.agora - execucao.confirmada_em).total_seconds()
        if idade <= ctx.politica.janela_atraso_segundos:
            return resultado(StatusConciliacao.PENDENTE, [Motivo.AGUARDANDO_REGISTRO_EXTERNO], externos=externos)
        if all(_ausencia_provada(execucao, r, ctx) for r in faltando):
            return resultado(StatusConciliacao.SEM_REGISTRO_EXTERNO, [Motivo.REGISTRO_EXTERNO_NAO_ENCONTRADO], externos=externos)
        return resultado(StatusConciliacao.NAO_VERIFICAVEL, [Motivo.COBERTURA_INSUFICIENTE], externos=externos)
    if any(g.status is StatusRegistroExterno.PENDENTE for _, g in resolvidas):
        return resultado(StatusConciliacao.PENDENTE, [Motivo.REGISTRO_EXTERNO_PENDENTE], externos=externos)
    if any(g.status is StatusRegistroExterno.CANCELADO for _, g in resolvidas):
        return resultado(StatusConciliacao.DIVERGENTE, [Motivo.CANCELADO_EXTERNAMENTE], externos=externos)

    diferencas, motivos = _comparar(execucao, resolvidas, ctx.politica)
    if motivos:
        return resultado(StatusConciliacao.DIVERGENTE, motivos, externos=externos, diferencas=diferencas)
    if indeterminada:  # nenhuma incompatibilidade explícita, mas a conta da evidência não está dita: não dá para afirmar
        return resultado(StatusConciliacao.NAO_VERIFICAVEL, [Motivo.CONTEXTO_INDETERMINADO], externos=externos)
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
        comprovado_g, nao_comprovado_g = _gastos(e, False)
        resultados[e.id] = antigo.model_copy(update={
            "status": StatusConciliacao.REVISAO, "motivos": tuple(dict.fromkeys((motivo, *antigo.motivos))), "efeito_no_progresso": Decimal(0),
            "gasto_comprovado": comprovado_g, "gasto_nao_comprovado": nao_comprovado_g,
        })


# -- progresso -----------------------------------------------------------------------------------------------------------------


def _progresso(resultados: Sequence[ResultadoExecucao], unicas: dict[str, Execucao]) -> tuple[ProgressoMeta, ...]:
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
        verificado: dict[str, Fraction] = defaultdict(Fraction)
        nao_verificado: dict[str, Fraction] = defaultdict(Fraction)
        gasto_ok: dict[str, Fraction] = defaultdict(Fraction)
        gasto_pendente: dict[str, Fraction] = defaultdict(Fraction)
        for r in itens:
            por_status[r.status.value] += 1
            e = unicas[r.execucao_id]
            moeda = r.moeda_gasto
            conciliada = r.status is StatusConciliacao.CONCILIADA
            if conciliada:
                taxas_ativo += _fr(e.taxa_no_ativo) * (1 if e.lado is LadoExecucao.COMPRA else -1)
            if moeda:
                gasto_ok[moeda] += _fr(r.gasto_comprovado)
                gasto_pendente[moeda] += _fr(r.gasto_nao_comprovado)
                alvo = verificado if conciliada else nao_verificado  # taxas só são "verificadas" se a execução foi conciliada
                alvo[moeda] += _fr(e.taxa_na_cotacao)
                nao_verificado[moeda] += _fr(e.custo_fixo_real)  # nunca há evidência externa do custo fixo
            for t in e.taxas_outros_ativos:
                (verificado if conciliada else nao_verificado)[t.ativo_id] += _fr(t.valor)
        pendencias = [f"{r.execucao_id}: {r.status.value} ({', '.join(m.value for m in r.motivos if m not in INFORMATIVOS)})"
                      for r in itens if r.status is not StatusConciliacao.CONCILIADA]
        if ativo is None:
            pendencias.append("meta com execuções de ativos diferentes")
        saida.append(ProgressoMeta(
            meta_id=meta_id, ativo_id=ativo, comprovado=comprovado, declarado=declarado, nao_comprovado=declarado - comprovado,
            por_status=dict(sorted(por_status.items())),
            taxas_no_ativo=_dec(taxas_ativo),
            custos=tuple(CustoPorAtivo(ativo_id=a, verificado=_dec(verificado.get(a, Fraction(0))), nao_verificado=_dec(nao_verificado.get(a, Fraction(0))))
                         for a in sorted(set(verificado) | set(nao_verificado))),
            gasto=tuple(GastoPorAtivo(ativo_id=a, comprovado=_dec(gasto_ok.get(a, Fraction(0))), nao_comprovado=_dec(gasto_pendente.get(a, Fraction(0))))
                        for a in sorted(set(gasto_ok) | set(gasto_pendente))),
            confirmacao=Confirmacao.INCOMPLETA if pendencias else Confirmacao.CONFIRMADA, pendencias=tuple(pendencias),
        ))
    return tuple(saida)


# -- API -----------------------------------------------------------------------------------------------------------------------------------


DOMINIO_VINCULO = "ubento.vinculo.v1"


def id_do_vinculo(vinculo: VinculoManual) -> str:
    """Identidade de um vínculo manual: o hash do seu conteúdo (autor, justificativa e instante inclusos)."""
    return hash_canonico(vinculo, DOMINIO_VINCULO)


def vinculos_vigentes(vinculos: Sequence[VinculoManual], revogacoes: Sequence[RevogacaoVinculo], agora: datetime) -> list[VinculoManual]:
    """Vínculos que valem em `agora`: já decididos e não revogados. Uma revogação só vale a partir do seu próprio instante,
    então reproduzir um instante anterior à correção devolve o mundo como ele era (e uma revogação não retroage ao vínculo)."""
    revogado_em: dict[str, datetime] = {}
    for r in revogacoes:
        if r.em <= agora:
            revogado_em[r.vinculo_id] = min(r.em, revogado_em.get(r.vinculo_id, r.em))
    saida = []
    for v in vinculos:
        if v.em > agora:
            continue
        quando = revogado_em.get(id_do_vinculo(v))
        if quando is not None and quando > v.em:
            continue
        saida.append(v)
    return saida


def hash_das_entradas(*, agora, politica, execucoes, externos, movimentacoes, saldos, coberturas, coberturas_execucoes, vinculos, revogacoes=(), metas=()) -> str:
    def lote(itens):
        return sorted(json_canonico(i) for i in itens)

    entradas = {
        "agora": agora, "politica": politica, "execucoes": lote(execucoes), "externos": lote(externos),
        "movimentacoes": lote(movimentacoes), "saldos": lote(saldos), "coberturas": lote(coberturas),
        "coberturas_execucoes": lote(coberturas_execucoes), "vinculos": lote(vinculos),
    }
    if metas:  # o contexto das metas também faz parte das entradas (sem metas, o hash é o de sempre)
        entradas["metas"] = lote(metas)
    if revogacoes:  # só entra quando existe: relatórios sem revogação mantêm exatamente o mesmo hash de antes
        entradas["revogacoes"] = lote(revogacoes)
    return hash_canonico(entradas, DOMINIO_ENTRADAS)


def conciliar(
    execucoes: Sequence[Execucao],
    externos: Sequence[RegistroExterno],
    *,
    politica: PoliticaConciliacao,
    agora: datetime,
    movimentacoes: Sequence[Movimentacao] = (),
    saldos: Sequence[SaldoObservado] = (),
    coberturas: Sequence[Cobertura] = (),
    coberturas_execucoes: Sequence[CoberturaExecucoes] = (),
    vinculos: Sequence[VinculoManual] = (),
    revogacoes: Sequence[RevogacaoVinculo] = (),
    metas: Sequence[Meta] = (),
) -> RelatorioConciliacao:
    """Concilia o que era conhecido em `agora`. Mesmas entradas e mesmo `agora` → mesmo relatório (mesmo hash)."""
    hash_entradas = hash_das_entradas(agora=agora, politica=politica, execucoes=execucoes, externos=externos,
                                      movimentacoes=movimentacoes, saldos=saldos, coberturas=coberturas,
                                      coberturas_execucoes=coberturas_execucoes, vinculos=vinculos, revogacoes=revogacoes, metas=metas)
    # só existe o que já tinha chegado em `agora`
    execucoes_v = [e for e in execucoes if e.confirmada_em <= agora]
    externos_v = [r for r in externos if r.recebido_em <= agora]
    vinculos_v = vinculos_vigentes(vinculos, revogacoes, agora)
    coberturas_v = [c for c in coberturas_execucoes if c.consultada_em <= agora]

    unicas, duplicadas, conflitantes_int = _unicas(execucoes_v)
    atual, conflitantes_ext, corrigidas, reimportadas = _historia_externa(externos_v)
    ctx = _Contexto(politica=politica, agora=agora, coberturas=coberturas_v, atual=atual, conflitantes=conflitantes_ext, corrigidas=corrigidas,
                    reimportadas=reimportadas, metas={m.id: m for m in metas})

    refs_por_exec = {id_: _referencias(e, vinculos_v) for id_, e in unicas.items()}
    validos = set(unicas) - conflitantes_int
    _alocacoes(unicas, validos, refs_por_exec, ctx)

    resultados = {
        id_: _avaliar(unicas[id_], refs_por_exec[id_], ctx, id_ in duplicadas, id_ in conflitantes_int)
        for id_ in sorted(unicas)
    }
    _revisar_estornos(resultados, unicas, refs_por_exec, ctx)

    orfaos = tuple(
        ResultadoExterno(
            fonte_id=c[0], id_externo=c[1], versao=r.versao, ativo_id=r.ativo_id, lado=r.lado, quantidade=r.quantidade, preco=r.preco,
            moeda_cotacao_id=r.moeda_cotacao_id, taxas=r.taxas, mercado_id=r.mercado_id, conta_id=r.conta_id, origem=r.origem,
            status=r.status, executado_em=r.executado_em, recebido_em=r.recebido_em, estorna_id_externo=r.estorna_id_externo)
        for c, r in sorted(atual.items())
        if c not in ctx.reivindicadas and r.status is not StatusRegistroExterno.CANCELADO
    )
    lista = tuple(resultados[i] for i in sorted(resultados))
    progresso = _progresso(lista, unicas)
    saldos_resultado = conciliar_saldos(
        [s for s in saldos if s.recebido_em <= agora], [m for m in movimentacoes if m.recebido_em <= agora],
        coberturas, atual, politica,
    )
    confirmada = all(p.confirmacao is Confirmacao.CONFIRMADA for p in progresso) and not (politica.orfaos_bloqueiam_confirmacao and orfaos)
    relatorio = RelatorioConciliacao(
        agora=agora, hash_entradas=hash_entradas, execucoes=lista, orfaos=orfaos, saldos=saldos_resultado, progresso=progresso,
        confirmacao=Confirmacao.CONFIRMADA if confirmada else Confirmacao.INCOMPLETA,
        metas_validadas=tuple(sorted(ctx.metas)), fontes_autorizadas=politica.fontes_autorizadas,
    )
    return relatorio.model_copy(update={"hash_saida": hash_canonico(relatorio, DOMINIO_SAIDA)})
