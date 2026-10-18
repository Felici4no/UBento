import random
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from ubento.nucleo.canonico import ErroCanonico, canonicalizar, hash_canonico, hash_contrato, hash_documento, json_canonico
from ubento.nucleo.carregador import carregar_arquivo
from ubento.nucleo.esquema import Analise, Ativacao, Meta

EXEMPLOS = Path(__file__).resolve().parents[2] / "exemplos" / "nucleo"


@pytest.fixture(scope="module")
def meta():
    return carregar_arquivo(Meta, EXEMPLOS / "meta_exemplo.yaml")


@pytest.fixture(scope="module")
def analise():
    return carregar_arquivo(Analise, EXEMPLOS / "analise_exemplo.yaml")


def test_json_canonico_ordena_chaves_e_remove_espacos():
    assert json_canonico({"b": 1, "a": {"d": True, "c": None}}) == '{"a":{"c":null,"d":true},"b":1}'


def test_decimais_equivalentes_geram_o_mesmo_hash():
    a = {"orcamento": Decimal("1000"), "taxa": Decimal("0.0050")}
    b = {"taxa": Decimal("0.005"), "orcamento": Decimal("1000.00")}
    assert hash_canonico(a, "t") == hash_canonico(b, "t")
    assert hash_canonico(a, "t") != hash_canonico({**a, "taxa": Decimal("0.0051")}, "t")


def test_dominio_separa_hashes():
    assert hash_canonico({"a": 1}, "x") != hash_canonico({"a": 1}, "y")


def test_instantes_equivalentes_geram_o_mesmo_hash():
    utc = datetime(2026, 10, 18, 15, 0, tzinfo=timezone.utc)
    br = datetime(2026, 10, 18, 12, 0, tzinfo=timezone(timedelta(hours=-3)))
    assert json_canonico({"t": utc}) == json_canonico({"t": br}) == '{"t":"2026-10-18T15:00:00Z"}'


def test_float_e_conjunto_sao_erros():
    with pytest.raises(ErroCanonico):
        canonicalizar({"x": 0.1})
    with pytest.raises(ErroCanonico):
        canonicalizar({"x": {1, 2}})
    with pytest.raises(ErroCanonico):
        canonicalizar({"x": datetime(2026, 1, 1)})  # sem fuso


def test_texto_unicode_equivalente_tem_o_mesmo_hash():
    composto, decomposto = "ação", "ação"
    assert composto != decomposto
    assert json_canonico({"k": composto}) == json_canonico({"k": decomposto})


def test_ausencia_e_null_explicito(meta):
    com_null = json_canonico(meta)
    assert '"substitui_meta_id":null' in com_null  # campo opcional omitido aparece como null


def test_hash_do_contrato_e_estavel_e_reproduzivel(meta):
    h = hash_contrato(meta)
    assert len(h) == 64 and h == hash_contrato(meta.model_copy(deep=True))
    assert h == hash_contrato(Meta.model_validate(meta.model_dump(mode="json")))  # ida e volta pelo intercâmbio


def test_qualquer_termo_do_contrato_altera_o_hash(meta):
    base = hash_contrato(meta)
    alterado = meta.model_copy(update={"recursos": meta.recursos.model_copy(update={"orcamento": Decimal("1001"), "saldo_reservado": Decimal("1001")})})
    assert hash_contrato(alterado) != base
    novo_prazo = meta.objetivo.model_copy(update={"prazo": meta.objetivo.prazo + timedelta(seconds=1)})
    assert hash_contrato(meta.model_copy(update={"objetivo": novo_prazo})) != base


def test_ativacao_nao_entra_no_hash_do_contrato(meta):
    ativacao = Ativacao(meta_id=meta.id, contrato_hash=hash_contrato(meta), ativada_em="2026-10-19T10:00:00Z", responsavel="Fulano")
    outra = ativacao.model_copy(update={"ativada_em": ativacao.ativada_em + timedelta(days=1), "responsavel": "Ciclana"})
    assert hash_contrato(meta) == ativacao.contrato_hash == outra.contrato_hash  # estado/ativação não mudam o contrato


def test_a_meta_aponta_para_o_hash_real_da_analise(meta, analise):
    assert meta.analise_hash == hash_documento(analise)
    assert all(a.analise_hash == meta.analise_hash for a in meta.fundamentacao.aprovacoes)


def test_ordem_das_chaves_do_documento_original_nao_importa(meta):
    dados = meta.model_dump(mode="json")
    chaves = list(dados)
    random.Random(7).shuffle(chaves)
    embaralhado = {k: dados[k] for k in chaves}
    assert hash_contrato(Meta.model_validate(embaralhado)) == hash_contrato(meta)


# -- propriedades ----------------------------------------------------------------------------------

folhas = st.one_of(
    st.none(), st.booleans(), st.integers(-10**12, 10**12), st.text(max_size=12),
    st.decimals(allow_nan=False, allow_infinity=False, places=6, min_value=Decimal("-1e9"), max_value=Decimal("1e9")),
)
arvores = st.recursive(folhas, lambda filho: st.one_of(st.lists(filho, max_size=4), st.dictionaries(st.text(min_size=1, max_size=6), filho, max_size=4)), max_leaves=12)


def _embaralhar(valor, rng):
    if isinstance(valor, dict):
        itens = list(valor.items())
        rng.shuffle(itens)
        return {k: _embaralhar(v, rng) for k, v in itens}
    if isinstance(valor, list):
        return [_embaralhar(v, rng) for v in valor]
    return valor


@settings(max_examples=150)
@given(arvores, st.integers(0, 10_000))
def test_hash_nao_depende_da_ordem_das_chaves(arvore, semente):
    assert hash_canonico(arvore, "t") == hash_canonico(_embaralhar(arvore, random.Random(semente)), "t")


@settings(max_examples=150)
@given(arvores)
def test_json_canonico_e_idempotente_e_sem_espacos(arvore):
    import json

    texto = json_canonico(arvore)
    assert json_canonico(json.loads(texto)) == texto
    # compacto: idêntico a reserializar o que ele mesmo decodifica, sem espaço fora das strings
    # (não se pode testar a ausência de ", " no texto: o CONTEÚDO de uma string pode conter isso)
    assert texto == json.dumps(json.loads(texto), sort_keys=True, separators=(",", ":"), ensure_ascii=False)


@settings(max_examples=100)
@given(st.decimals(allow_nan=False, allow_infinity=False, places=6, min_value=Decimal("-1e9"), max_value=Decimal("1e9")), st.integers(1, 6))
def test_zeros_a_direita_nunca_mudam_o_hash(valor, extras):
    texto = f"{valor:f}"
    equivalente = Decimal(texto + ("0" * extras if "." in texto else "." + "0" * extras))
    assert equivalente == valor
    assert hash_canonico({"v": valor}, "t") == hash_canonico({"v": equivalente}, "t")
