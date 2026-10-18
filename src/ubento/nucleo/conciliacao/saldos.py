"""Conciliação de SALDOS: explica a variação de saldo observada com as movimentações conhecidas.

É deliberadamente separada da conciliação de execuções. Um resíduo aqui não prova erro de execução (pode ser depósito,
retirada, transferência ou ajuste não informado) e nunca altera o status de uma execução nem o progresso de uma meta.
"""

from __future__ import annotations

from collections import defaultdict
from decimal import Decimal
from fractions import Fraction
from typing import Sequence

from ..esquema import LadoExecucao
from ..tipos import normalizar_decimal
from .modelos import (
    Cobertura, Motivo, Movimentacao, PoliticaConciliacao, RegistroExterno, ResultadoSaldo, SaldoObservado,
    StatusRegistroExterno, StatusSaldo, TipoMovimentacao,
)


def _dec(valor: Fraction) -> Decimal:
    return Decimal(valor.numerator) / Decimal(valor.denominator)


def _coberto(coberturas: Sequence[Cobertura], fonte_id: str, ativo_id: str, inicio, fim) -> bool:
    return any(c.fonte_id == fonte_id and c.ativo_id == ativo_id and c.inicio <= inicio and c.fim >= fim for c in coberturas)


def _inconsistencias(movs: Sequence[Movimentacao], atual: dict[tuple[str, str], RegistroExterno], ativo_id: str) -> tuple[list[str], list[Motivo]]:
    """Confere movimentações ligadas a execuções externas (informativo; não muda status de execução)."""
    textos: list[str] = []
    motivos: list[Motivo] = []
    por_registro: dict[tuple[str, str], Fraction] = defaultdict(Fraction)
    for m in movs:
        if m.referencia_execucao_externa and m.tipo in (TipoMovimentacao.EXECUCAO, TipoMovimentacao.TAXA):
            por_registro[(m.fonte_id, m.referencia_execucao_externa)] += Fraction(m.quantidade)
    for chave in sorted(por_registro):
        reg = atual.get(chave)
        if reg is None or reg.ativo_id != ativo_id or reg.status is not StatusRegistroExterno.CONFIRMADO:
            continue
        taxa_ativo = sum((Fraction(t.valor) for t in reg.taxas if t.ativo_id == reg.ativo_id), Fraction(0))
        esperado = Fraction(reg.quantidade) - taxa_ativo
        esperado = esperado if reg.lado is LadoExecucao.COMPRA else -esperado
        if por_registro[chave] != esperado:
            textos.append(f"{chave[1]}: movimentação líquida {normalizar_decimal(_dec(por_registro[chave]))} ≠ esperada {normalizar_decimal(_dec(esperado))}")
            motivos.append(Motivo.MOVIMENTO_DE_EXECUCAO_DIVERGENTE)
    return textos, motivos


def conciliar_saldos(
    saldos: Sequence[SaldoObservado],
    movimentacoes: Sequence[Movimentacao],
    coberturas: Sequence[Cobertura],
    atual: dict[tuple[str, str], RegistroExterno],
    politica: PoliticaConciliacao,
) -> tuple[ResultadoSaldo, ...]:
    """Um resultado por intervalo entre observações consecutivas de (fonte, ativo)."""
    grupos: dict[tuple[str, str], list[SaldoObservado]] = defaultdict(list)
    for s in saldos:
        grupos[(s.fonte_id, s.ativo_id)].append(s)
    resultados: list[ResultadoSaldo] = []
    for (fonte_id, ativo_id) in sorted(grupos):
        pontos = sorted(grupos[(fonte_id, ativo_id)], key=lambda s: (s.observado_em, str(s.quantidade)))
        movs_ativo = [m for m in movimentacoes if m.fonte_id == fonte_id and m.ativo_id == ativo_id]
        if len(pontos) < 2:
            resultados.append(ResultadoSaldo(
                ativo_id=ativo_id, fonte_id=fonte_id, inicio=None, fim=pontos[0].observado_em, status=StatusSaldo.DADOS_INSUFICIENTES,
                saldo_final=pontos[0].quantidade, motivos=(Motivo.SALDO_AUSENTE,),
            ))
            continue
        for antes, depois in zip(pontos, pontos[1:]):
            dentro = sorted((m for m in movs_ativo if antes.observado_em < m.em <= depois.observado_em), key=lambda m: (m.em, m.id_externo))
            variacao = Fraction(depois.quantidade) - Fraction(antes.quantidade)
            base = dict(ativo_id=ativo_id, fonte_id=fonte_id, inicio=antes.observado_em, fim=depois.observado_em,
                        saldo_inicial=antes.quantidade, saldo_final=depois.quantidade, variacao_observada=_dec(variacao))
            if not _coberto(coberturas, fonte_id, ativo_id, antes.observado_em, depois.observado_em):
                resultados.append(ResultadoSaldo(**base, status=StatusSaldo.DADOS_INSUFICIENTES, motivos=(Motivo.COBERTURA_INSUFICIENTE,)))
                continue
            explicada = sum((Fraction(m.quantidade) for m in dentro), Fraction(0))
            residuo = variacao - explicada
            por_tipo: dict[str, Fraction] = defaultdict(Fraction)
            for m in dentro:
                por_tipo[m.tipo.value] += Fraction(m.quantidade)
            textos, motivos_inc = _inconsistencias(dentro, atual, ativo_id)
            ok = abs(residuo) <= Fraction(politica.tolerancia_saldo)
            resultados.append(ResultadoSaldo(
                **base, status=StatusSaldo.EXPLICADA if ok else StatusSaldo.NAO_EXPLICADA,
                variacao_explicada=_dec(explicada), residuo=_dec(residuo),
                por_tipo={k: _dec(v) for k, v in sorted(por_tipo.items())},
                motivos=tuple(dict.fromkeys(([] if ok else [Motivo.DIFERENCA_NAO_EXPLICADA]) + motivos_inc)),
                inconsistencias=tuple(textos),
            ))
    return tuple(sorted(resultados, key=lambda r: (r.ativo_id, r.fonte_id, r.fim or r.inicio)))
