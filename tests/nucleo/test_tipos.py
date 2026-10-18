from datetime import datetime, timedelta, timezone
from decimal import Decimal

import pytest
from hypothesis import given
from hypothesis import strategies as st
from pydantic import BaseModel, ValidationError

from ubento.nucleo.tipos import (
    ErroDeTipo, Fracao, Instante, Positivo, Tri, arredondar_para_baixo, arredondar_para_cima, formatar_instante,
    normalizar_decimal, para_decimal,
)


class Caixa(BaseModel):
    valor: Positivo
    quando: Instante


def test_decimal_aceita_texto_inteiro_e_decimal():
    assert para_decimal("1.50") == Decimal("1.5")
    assert para_decimal(3) == Decimal(3)
    assert para_decimal(Decimal("2")) == Decimal(2)


@pytest.mark.parametrize("ruim", [0.1, True, "abc", "", "NaN", "Infinity", "-Infinity", "1e999999", None, [1]])
def test_decimal_rejeita_o_que_nao_e_texto_decimal_seguro(ruim):
    with pytest.raises(ErroDeTipo):
        para_decimal(ruim)


def test_float_nunca_vira_decimal_silenciosamente():
    with pytest.raises(ValidationError):
        Caixa(valor=0.1, quando="2026-10-18T12:00:00Z")


@pytest.mark.parametrize("texto", ["1", "1.0", "1.00", "1.000000", "+1", "0.1e1", "10E-1"])
def test_decimais_equivalentes_tem_a_mesma_forma_canonica(texto):
    assert normalizar_decimal(para_decimal(texto)) == "1"


def test_formas_canonicas_especiais():
    assert normalizar_decimal(Decimal("-0")) == "0"
    assert normalizar_decimal(Decimal("0.000")) == "0"
    assert normalizar_decimal(Decimal("1E+3")) == "1000"  # sem expoente
    assert normalizar_decimal(Decimal("0.0050")) == "0.005"
    assert normalizar_decimal(Decimal("-12.340")) == "-12.34"


def test_fracao_so_aceita_entre_zero_e_um():
    class Taxa(BaseModel):
        t: Fracao

    assert Taxa(t="0.005").t == Decimal("0.005")
    for ruim in ("1.01", "-0.1", "5"):
        with pytest.raises(ValidationError):
            Taxa(t=ruim)


def test_instante_exige_fuso_e_normaliza_para_utc():
    a = Caixa(valor="1", quando="2026-10-18T12:00:00-03:00")
    assert a.quando.utcoffset() == timedelta(0)
    assert formatar_instante(a.quando) == "2026-10-18T15:00:00Z"
    assert Caixa(valor="1", quando="2026-10-18T15:00:00Z").quando == a.quando
    with pytest.raises(ValidationError):
        Caixa(valor="1", quando="2026-10-18T12:00:00")  # sem fuso
    with pytest.raises(ValidationError):
        Caixa(valor="1", quando=datetime(2026, 10, 18, 12))  # sem fuso


def test_formatar_instante_so_mostra_microssegundos_quando_existem():
    tz = timezone(timedelta(hours=2))
    assert formatar_instante(datetime(2026, 1, 1, 0, 0, 0, tzinfo=tz)) == "2025-12-31T22:00:00Z"
    assert formatar_instante(datetime(2026, 1, 1, 0, 0, 0, 5, tzinfo=tz)) == "2025-12-31T22:00:00.000005Z"


def test_tri_tem_tres_valores_distintos():
    assert {t.value for t in Tri} == {"verdadeiro", "falso", "indeterminado"}


# -- arredondamento: cada restrição escolhe a direção ---------------------------------------


def test_preco_maximo_do_documento_arredonda_para_baixo_sem_estourar_o_orcamento():
    bruto = (Decimal(1000) - 5) / (Decimal(100) * Decimal("1.005"))
    preco = arredondar_para_baixo(bruto, Decimal("0.0001"))
    assert preco == Decimal("9.9004")
    assert Decimal(100) * preco * Decimal("1.005") + 5 <= 1000
    para_cima = arredondar_para_cima(bruto, Decimal("0.0001"))
    assert Decimal(100) * para_cima * Decimal("1.005") + 5 > 1000  # a direção errada estoura


def test_quantidade_comprada_a_9_91_nao_fecha_a_meta():
    quantidade = arredondar_para_baixo(Decimal(995) / (Decimal("9.91") * Decimal("1.005")), Decimal("0.01"))
    assert quantidade == Decimal("99.90") and quantidade < 100


def test_quantidade_minima_arredonda_para_cima_no_incremento():
    assert arredondar_para_cima(Decimal("99.901"), Decimal("0.01")) == Decimal("99.91")
    assert arredondar_para_cima(Decimal("99.90"), Decimal("0.01")) == Decimal("99.90")


def test_passo_invalido():
    for passo in (Decimal(0), Decimal("-0.1")):
        with pytest.raises(ValueError):
            arredondar_para_baixo(Decimal(1), passo)


decimais = st.decimals(min_value=Decimal("-1000000"), max_value=Decimal("1000000"), allow_nan=False, allow_infinity=False, places=8)
passos = st.sampled_from([Decimal("1"), Decimal("0.5"), Decimal("0.01"), Decimal("0.0001"), Decimal("25")])


@given(decimais, passos)
def test_propriedades_do_arredondamento(valor, passo):
    baixo, cima = arredondar_para_baixo(valor, passo), arredondar_para_cima(valor, passo)
    assert baixo <= valor <= cima
    assert baixo % passo == 0 and cima % passo == 0
    assert cima - baixo in (Decimal(0), passo)
    assert (baixo == cima) == (valor % passo == 0)


@given(decimais)
def test_forma_canonica_e_estavel(valor):
    texto = normalizar_decimal(valor)
    assert Decimal(texto) == valor
    assert normalizar_decimal(Decimal(texto)) == texto
    assert "E" not in texto and "e" not in texto
