"""Motor de regras mínimo para o avaliador de metas.

Só o necessário para D3: avalia a árvore de condições do contrato (`all`, `any`, `not`, comparações) contra um
`Snapshot` de observações. Cada condição devolve verdadeiro/falso/indeterminado com explicação estruturada.

Dado ausente, de qualidade ruim, vencido, de unidade incompatível ou de fontes divergentes dá `indeterminado`,
nunca um palpite. Não há média silenciosa entre fontes. O catálogo completo de métricas é a Fase 2; aqui uma
métrica é só "a observação mais recente e válida" de (métrica, ativo, mercado).
"""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from fractions import Fraction
from typing import Mapping, Sequence

from .canonico import hash_canonico
from .esquema import (
    Algum, Comparacao, Modelo, Nao, Observacao, OperandoMetrica, OperandoValor, QualidadeDado, ResultadoCondicao, Todos,
    Tolerancia,
)
from .tipos import Tri, formatar_instante, normalizar_decimal

DOMINIO_SNAPSHOT = "ubento.snapshot.v1"
OPERADORES = {
    "eq": lambda a, b: a == b, "neq": lambda a, b: a != b, "gt": lambda a, b: a > b,
    "gte": lambda a, b: a >= b, "lt": lambda a, b: a < b, "lte": lambda a, b: a <= b,
}


class Snapshot(Modelo):
    """Observações disponíveis para uma avaliação. Entra no hash de entradas, o que permite reproduzir o resultado."""

    observacoes: tuple[Observacao, ...] = ()

    @property
    def id(self) -> str:
        return hash_canonico(sorted(self.observacoes, key=lambda o: o.id), DOMINIO_SNAPSHOT)


# -- lógica de três valores ---------------------------------------------------------------------------------------------------


def todos(valores: Sequence[Tri]) -> Tri:
    if any(v is Tri.FALSO for v in valores):
        return Tri.FALSO
    return Tri.VERDADEIRO if all(v is Tri.VERDADEIRO for v in valores) else Tri.INDETERMINADO


def algum(valores: Sequence[Tri]) -> Tri:
    if any(v is Tri.VERDADEIRO for v in valores):
        return Tri.VERDADEIRO
    return Tri.FALSO if all(v is Tri.FALSO for v in valores) else Tri.INDETERMINADO


def nao(valor: Tri) -> Tri:
    return {Tri.VERDADEIRO: Tri.FALSO, Tri.FALSO: Tri.VERDADEIRO, Tri.INDETERMINADO: Tri.INDETERMINADO}[valor]


# -- leitura de uma métrica --------------------------------------------------------------------------------------------------------


class _Leitura:
    def __init__(self, valor: Decimal | None, unidade: str | None, motivo: str | None, explicacao: dict, evidencia_em: datetime | None):
        self.valor, self.unidade, self.motivo, self.explicacao, self.evidencia_em = valor, unidade, motivo, explicacao, evidencia_em


def _ler(op: OperandoMetrica, snap: Snapshot, agora: datetime, validades: Mapping[str, int], tolerancias: Mapping[tuple[str, str], Tolerancia]) -> _Leitura:
    base = {"metrica": op.metrica_id}
    candidatas = [o for o in snap.observacoes if o.metrica_id == op.metrica_id and o.ativo_id == op.ativo_id
                  and (op.mercado_id is None or o.mercado_id == op.mercado_id) and o.coletado_em <= agora]
    if not candidatas:
        return _Leitura(None, None, "sem_observacao", base, None)
    por_fonte: dict[str, Observacao] = {}
    for o in sorted(candidatas, key=lambda o: (o.observado_em, o.id)):
        por_fonte[o.fonte_id] = o  # a mais recente de cada fonte
    ruins = sorted({o.qualidade.value for o in por_fonte.values() if o.qualidade is not QualidadeDado.DISPONIVEL})
    boas = [o for o in por_fonte.values() if o.qualidade is QualidadeDado.DISPONIVEL and o.valor is not None]
    if not boas:
        return _Leitura(None, None, f"qualidade_{ruins[0]}" if ruins else "sem_observacao", base, None)
    limite = validades.get(op.metrica_id)
    if limite is None:
        return _Leitura(None, None, "validade_nao_configurada", base, None)
    frescas = [o for o in boas if (agora - o.observado_em).total_seconds() <= limite]
    if not frescas:
        idade = int((agora - max(o.observado_em for o in boas)).total_seconds())
        return _Leitura(None, None, "dado_vencido", {**base, "idade_s": idade, "limite_s": limite}, None)
    frescas.sort(key=lambda o: o.fonte_id)
    escolhida = frescas[0]
    if len({o.valor for o in frescas}) > 1:  # fontes discordam: só aceita com política explícita e dentro da tolerância
        mercado = escolhida.mercado_id
        tol = tolerancias.get((op.metrica_id, mercado))
        if tol is None:
            return _Leitura(None, None, "fontes_divergentes_sem_politica", base, None)
        ref = Fraction(escolhida.valor)
        for o in frescas[1:]:
            desvio_t = abs((o.observado_em - escolhida.observado_em).total_seconds())
            rel = abs(Fraction(o.valor) - ref) / abs(ref) if ref != 0 else Fraction(0 if o.valor == 0 else 1)
            if desvio_t > tol.diferenca_maxima_horario_segundos or rel > Fraction(tol.tolerancia_relativa):
                return _Leitura(None, None, "fontes_divergentes", base, None)
    explicacao = {**base, "valor": normalizar_decimal(escolhida.valor), "unidade": escolhida.unidade, "fonte": escolhida.fonte_id,
                  "observado_em": formatar_instante(escolhida.observado_em), "idade_s": int((agora - escolhida.observado_em).total_seconds()),
                  "fontes": len(frescas)}
    return _Leitura(escolhida.valor, escolhida.unidade, None, explicacao, escolhida.observado_em)


# -- avaliação --------------------------------------------------------------------------------------------------------------------------


def avaliar_condicao(cond, snap: Snapshot, agora: datetime, validades: Mapping[str, int] | None = None,
                     tolerancias: Mapping[tuple[str, str], Tolerancia] | None = None) -> list[ResultadoCondicao]:
    """Resultado da condição e de todas as suas filhas (a raiz é o último item), em ordem de percurso."""
    validades, tolerancias = validades or {}, tolerancias or {}
    return _avaliar(cond, snap, agora, validades, tolerancias)


def _avaliar(cond, snap, agora, validades, tolerancias) -> list[ResultadoCondicao]:
    if isinstance(cond, (Todos, Algum)):
        filhos = [r for f in cond.itens for r in _avaliar(f, snap, agora, validades, tolerancias)]
        raizes = [r for r, f in zip(_raizes(filhos, cond.itens), cond.itens)]
        resultado = (todos if isinstance(cond, Todos) else algum)([r.resultado for r in raizes])
        return filhos + [ResultadoCondicao(condicao_id=cond.id, resultado=resultado, explicacao={"operador": cond.op, "itens": len(cond.itens)})]
    if isinstance(cond, Nao):
        filhos = _avaliar(cond.item, snap, agora, validades, tolerancias)
        return filhos + [ResultadoCondicao(condicao_id=cond.id, resultado=nao(filhos[-1].resultado), explicacao={"operador": "not"})]
    return [_comparar(cond, snap, agora, validades, tolerancias)]


def _raizes(resultados: list[ResultadoCondicao], itens) -> list[ResultadoCondicao]:
    """Pega, na lista achatada, o resultado da raiz de cada item (identificado pelo id)."""
    por_id = {r.condicao_id: r for r in resultados}
    return [por_id[i.id] for i in itens]


def _operando(op, snap, agora, validades, tolerancias, lado: str) -> _Leitura:
    if isinstance(op, OperandoValor):
        return _Leitura(op.valor, op.unidade, None, {f"{lado}_valor": normalizar_decimal(op.valor)}, None)
    leitura = _ler(op, snap, agora, validades, tolerancias)
    return _Leitura(leitura.valor, leitura.unidade, leitura.motivo, {f"{lado}_{k}": v for k, v in leitura.explicacao.items()}, leitura.evidencia_em)


def _comparar(cond: Comparacao, snap, agora, validades, tolerancias) -> ResultadoCondicao:
    esq = _operando(cond.esquerda, snap, agora, validades, tolerancias, "esq")
    dir_ = _operando(cond.direita, snap, agora, validades, tolerancias, "dir")
    explicacao = {**esq.explicacao, **dir_.explicacao, "operador": cond.op}
    motivo = esq.motivo or dir_.motivo
    if motivo is None and esq.unidade != dir_.unidade:
        motivo = "unidade_incompativel"
        explicacao.update(esq_unidade=esq.unidade, dir_unidade=dir_.unidade)
    if motivo is not None:
        return ResultadoCondicao(condicao_id=cond.id, resultado=Tri.INDETERMINADO, explicacao={**explicacao, "motivo": motivo})
    verdadeiro = OPERADORES[cond.op](esq.valor, dir_.valor)
    instantes = [t for t in (esq.evidencia_em, dir_.evidencia_em) if t is not None]
    if instantes:
        explicacao["evidencia_em"] = formatar_instante(max(instantes))  # quando a condição foi OBSERVADA
    return ResultadoCondicao(condicao_id=cond.id, resultado=Tri.VERDADEIRO if verdadeiro else Tri.FALSO, explicacao=explicacao)


def avaliar_grupo(condicoes: Sequence, snap: Snapshot, agora: datetime, validades=None, tolerancias=None, modo: str = "todos") -> tuple[Tri, list[ResultadoCondicao]]:
    """Avalia uma lista obrigatória: `todos` (bloqueios, entrada) ou `algum` (invalidação). Lista vazia é erro de contrato."""
    if not condicoes:
        raise ValueError("lista de condições obrigatória não pode ser vazia")
    resultados: list[ResultadoCondicao] = []
    raizes: list[Tri] = []
    for c in condicoes:
        r = avaliar_condicao(c, snap, agora, validades, tolerancias)
        resultados += r
        raizes.append(r[-1].resultado)
    return (todos if modo == "todos" else algum)(raizes), resultados


def evidencia_da_condicao(resultados: Sequence[ResultadoCondicao]) -> datetime | None:
    """Maior instante de observação usado pelas condições que valeram verdadeiro."""
    from .tipos import para_instante

    momentos = [para_instante(r.explicacao["evidencia_em"]) for r in resultados
                if r.resultado is Tri.VERDADEIRO and isinstance(r.explicacao.get("evidencia_em"), str)]
    return max(momentos) if momentos else None


