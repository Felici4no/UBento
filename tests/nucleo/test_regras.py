from datetime import UTC, datetime, timedelta
from decimal import Decimal
from itertools import product

import pytest
from hypothesis import given
from hypothesis import strategies as st
from pydantic import TypeAdapter

from ubento.nucleo.esquema import Condicao, Observacao, Tolerancia
from ubento.nucleo.regras import Snapshot, algum, avaliar_condicao, avaliar_grupo, evidencia_da_condicao, nao, todos
from ubento.nucleo.tipos import Tri

AGORA = datetime(2026, 10, 20, 12, 0, tzinfo=UTC)
V, F, I = Tri.VERDADEIRO, Tri.FALSO, Tri.INDETERMINADO
VALIDADES = {"preco": 600}
_adapter = TypeAdapter(Condicao)


def obs(valor="10", *, id_="o1", fonte="f1", minutos=-1, unidade="USD", qualidade="disponivel", coletado_min=None, mercado="m1", metrica="preco"):
    t = AGORA + timedelta(minutes=minutos)
    extra = {} if qualidade == "disponivel" else {"motivo_ausencia": "sem dado da fonte"}
    return Observacao(id=id_, ativo_id="tokx", metrica_id=metrica, fonte_id=fonte, mercado_id=mercado, unidade=unidade,
                      valor=None if qualidade == "ausente" else valor, qualidade=qualidade, origem="simulado", observado_em=t,
                      coletado_em=AGORA + timedelta(minutes=coletado_min) if coletado_min is not None else t, **extra)


def cmp(op="gt", valor="5", unidade="USD", id_="c1", metrica="preco"):
    return _adapter.validate_python({
        "id": id_, "op": op,
        "esquerda": {"tipo": "metrica", "metrica_id": metrica, "ativo_id": "tokx", "mercado_id": "m1"},
        "direita": {"tipo": "valor", "valor": valor, "unidade": unidade},
    })


def avaliar(cond, *observacoes, validades=VALIDADES, tolerancias=None):
    r = avaliar_condicao(cond, Snapshot(observacoes=tuple(observacoes)), AGORA, validades, tolerancias)
    return r[-1]


@pytest.mark.parametrize("op, valor, esperado", [
    ("gt", "9", V), ("gt", "10", F), ("gte", "10", V), ("gte", "11", F), ("lt", "11", V), ("lt", "10", F),
    ("lte", "10", V), ("lte", "9", F), ("eq", "10", V), ("eq", "10.0", V), ("eq", "11", F), ("neq", "11", V), ("neq", "10", F),
])
def test_operadores_com_decimal_exato(op, valor, esperado):
    assert avaliar(cmp(op, valor), obs("10")).resultado is esperado


def test_decimal_nao_sofre_erro_de_ponto_flutuante():
    assert avaliar(cmp("eq", "0.3"), obs("0.3")).resultado is V
    assert avaliar(cmp("lte", "0.3"), obs("0.30000000000000004")).resultado is F  # com float isso daria verdadeiro


@pytest.mark.parametrize("observacoes, validades, motivo", [
    ([], VALIDADES, "sem_observacao"),
    ([obs(minutos=-30)], VALIDADES, "dado_vencido"),  # 30 min > 600 s
    ([obs()], {}, "validade_nao_configurada"),
    ([obs(qualidade="ausente")], VALIDADES, "qualidade_ausente"),
    ([obs(unidade="EUR")], VALIDADES, "unidade_incompativel"),
    ([obs(coletado_min=+5)], VALIDADES, "sem_observacao"),  # coletada depois de `agora`: ainda não existe
    ([obs(mercado="outro")], VALIDADES, "sem_observacao"),
])
def test_dado_ruim_nunca_vira_verdadeiro_nem_falso(observacoes, validades, motivo):
    r = avaliar(cmp(), *observacoes, validades=validades)
    assert r.resultado is I and r.explicacao["motivo"] == motivo


def test_usa_a_observacao_mais_recente_da_fonte():
    r = avaliar(cmp("gt", "5"), obs("1", id_="velha", minutos=-8), obs("10", id_="nova", minutos=-1))
    assert r.resultado is V and r.explicacao["esq_valor"] == "10"


def test_fontes_divergentes_exigem_politica_explicita_e_nunca_fazem_media():
    a, b = obs("100", id_="a", fonte="f1"), obs("100.4", id_="b", fonte="f2")
    assert avaliar(cmp("gt", "50"), a, b).explicacao["motivo"] == "fontes_divergentes_sem_politica"
    tolerante = {("preco", "m1"): Tolerancia(metrica_id="preco", mercado_id="m1", diferenca_maxima_horario_segundos=60, tolerancia_relativa="0.005")}
    ok = avaliar(cmp("gt", "50"), a, b, tolerancias=tolerante)
    assert ok.resultado is V and ok.explicacao["esq_fontes"] == 2
    apertada = {("preco", "m1"): Tolerancia(metrica_id="preco", mercado_id="m1", diferenca_maxima_horario_segundos=60, tolerancia_relativa="0.001")}
    assert avaliar(cmp("gt", "50"), a, b, tolerancias=apertada).explicacao["motivo"] == "fontes_divergentes"
    atrasada = obs("100.1", id_="c", fonte="f3", minutos=-9)
    assert avaliar(cmp("gt", "50"), a, atrasada, tolerancias=tolerante).explicacao["motivo"] == "fontes_divergentes"  # horários distantes


def test_fontes_que_concordam_nao_precisam_de_politica():
    assert avaliar(cmp("gt", "50"), obs("100", id_="a", fonte="f1"), obs("100", id_="b", fonte="f2")).resultado is V


def test_evidencia_e_o_instante_da_observacao():
    resultados = avaliar_condicao(cmp(), Snapshot(observacoes=(obs(minutos=-3),)), AGORA, VALIDADES)
    assert evidencia_da_condicao(resultados) == AGORA - timedelta(minutes=3)


# -- composição ------------------------------------------------------------------------------------------------------------------------------------------


def _todos(*itens):
    return _adapter.validate_python({"id": "t", "op": "all", "itens": [i.model_dump(mode="json") for i in itens]})


def _algum(*itens):
    return _adapter.validate_python({"id": "a", "op": "any", "itens": [i.model_dump(mode="json") for i in itens]})


def _nao(item):
    return _adapter.validate_python({"id": "n", "op": "not", "item": item.model_dump(mode="json")})


def test_all_any_not_com_dado_indeterminado():
    verdadeiro, falso = cmp("gt", "5", id_="v"), cmp("gt", "50", id_="f")
    indeterminado = cmp("gt", "5", id_="i", metrica="outra")  # sem observação dessa métrica
    snap = Snapshot(observacoes=(obs("10"),))

    def ver(cond):
        return avaliar_condicao(cond, snap, AGORA, VALIDADES)[-1].resultado

    assert ver(_todos(verdadeiro, indeterminado)) is I and ver(_todos(falso, indeterminado)) is F
    assert ver(_algum(falso, indeterminado)) is I and ver(_algum(verdadeiro, indeterminado)) is V
    assert ver(_nao(indeterminado)) is I and ver(_nao(falso)) is V


def test_grupo_obrigatorio_todos_x_algum_e_lista_vazia():
    snap = Snapshot(observacoes=(obs("10"),))
    v, f = cmp("gt", "5", id_="v"), cmp("gt", "50", id_="f")
    assert avaliar_grupo([v, f], snap, AGORA, VALIDADES, modo="todos")[0] is F
    assert avaliar_grupo([v, f], snap, AGORA, VALIDADES, modo="algum")[0] is V
    with pytest.raises(ValueError):
        avaliar_grupo([], snap, AGORA, VALIDADES)


def test_bloqueio_indeterminado_nao_e_contornado_por_um_sinal_favoravel():
    """`algum` favorável não pode esconder um bloqueio obrigatório indeterminado (avaliados em grupos separados)."""
    snap = Snapshot(observacoes=(obs("10"),))
    bloqueio, _ = avaliar_grupo([cmp("gt", "5", id_="x", metrica="falta")], snap, AGORA, VALIDADES, modo="todos")
    sinal, _ = avaliar_grupo([cmp("gt", "5", id_="y")], snap, AGORA, VALIDADES, modo="algum")
    assert sinal is V and bloqueio is I


tri = st.sampled_from(list(Tri))


@given(st.lists(tri, min_size=1, max_size=5))
def test_logica_de_kleene_e_de_morgan(valores):
    ordem = {F: 0, I: 1, V: 2}
    assert ordem[todos(valores)] == min(ordem[v] for v in valores) and ordem[algum(valores)] == max(ordem[v] for v in valores)
    assert nao(todos(valores)) is algum([nao(v) for v in valores]) and nao(algum(valores)) is todos([nao(v) for v in valores])


def test_todas_as_combinacoes_de_dois_valores():
    for a, b in product(Tri, repeat=2):
        assert todos([a, b]) is todos([b, a]) and algum([a, b]) is algum([b, a])
    assert Decimal("0.1") + Decimal("0.2") == Decimal("0.3")
