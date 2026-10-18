from pathlib import Path

import pytest
from pydantic import BaseModel

from ubento.nucleo.carregador import (
    ErroDeCarga, ErroDeValidacao, carregar_arquivo, carregar_texto, ler_json, ler_yaml, para_json, para_yaml, validar,
)
from ubento.nucleo.canonico import hash_contrato, hash_documento
from ubento.nucleo.esquema import Analise, Meta
from ubento.nucleo.tipos import Positivo

EXEMPLOS = Path(__file__).resolve().parents[2] / "exemplos" / "nucleo"


class Pequeno(BaseModel):
    model_config = {"extra": "forbid"}
    valor: Positivo


# -- YAML -------------------------------------------------------------------------------------


def test_yaml_valido_e_lido_como_dict_comum():
    dados = ler_yaml("a: 1\nb: [x, y]\nc: {d: null}\n")
    assert dados == {"a": 1, "b": ["x", "y"], "c": {"d": None}}
    assert type(dados) is dict and type(dados["b"]) is list


@pytest.mark.parametrize("texto, trecho", [
    ("a: 1\na: 2\n", "duplic"),
    ("valor: 0.05\n", "sem aspas"),
    ("valor: 1e3\n", "sem aspas"),
    ("quando: 2026-10-18\n", "aspas"),
    ("quando: 2026-10-18T12:00:00Z\n", "aspas"),
    ("1: um\n", "chave não textual"),
    ("a: [\n", "YAML inválido"),
])
def test_yaml_recusa_o_que_e_ambiguo(texto, trecho):
    with pytest.raises(ErroDeCarga) as erro:
        ler_yaml(texto)
    assert trecho in str(erro.value)


def test_yaml_nao_instancia_objetos():
    with pytest.raises(ErroDeCarga):
        ler_yaml("x: !!python/object/apply:os.system ['echo oi']\n")


def test_yaml_circular_e_profundo_sao_recusados():
    with pytest.raises(ErroDeCarga):
        ler_yaml("a: &a [*a]\n")
    with pytest.raises(ErroDeCarga, match="profunda"):
        ler_yaml("[" * 60 + "]" * 60)


def test_yaml_gigante_e_recusado():
    with pytest.raises(ErroDeCarga, match="maior"):
        ler_yaml("a: " + "x" * 2_000_000)


def test_yaml_mantem_numeros_com_aspas_como_texto():
    assert ler_yaml('valor: "0.05"\nn: 7\n') == {"valor": "0.05", "n": 7}


# -- JSON -------------------------------------------------------------------------------------


@pytest.mark.parametrize("texto, trecho", [
    ('{"a":1,"a":2}', "duplicada"),
    ('{"v":0.5}', "sem aspas"),
    ('{"v":NaN}', "constante"),
    ('{"v":Infinity}', "constante"),
    ('{"v":', "JSON inválido"),
])
def test_json_recusa_o_que_e_ambiguo(texto, trecho):
    with pytest.raises(ErroDeCarga) as erro:
        ler_json(texto)
    assert trecho in str(erro.value)


def test_json_aceita_inteiros_e_textos():
    assert ler_json('{"a":[1,"2",true,null]}') == {"a": [1, "2", True, None]}


# -- validação ---------------------------------------------------------------------------------


def test_validar_lista_todos_os_problemas_com_caminho():
    with pytest.raises(ErroDeValidacao) as erro:
        validar(Pequeno, {"valor": "-1", "extra": 1})
    caminhos = {e.caminho for e in erro.value.erros}
    assert caminhos == {"valor", "extra"}


def test_carregar_texto_em_yaml_e_json():
    assert carregar_texto(Pequeno, 'valor: "2"').valor == 2
    assert carregar_texto(Pequeno, '{"valor":"2"}', "json").valor == 2
    with pytest.raises(ErroDeCarga):
        carregar_texto(Pequeno, "valor: 2", "xml")


def test_carregar_arquivo_valida_extensao(tmp_path):
    (tmp_path / "x.txt").write_text("valor: 1")
    with pytest.raises(ErroDeCarga):
        carregar_arquivo(Pequeno, tmp_path / "x.txt")


# -- exemplos e ida-e-volta --------------------------------------------------------------------------


@pytest.fixture(scope="module")
def analise():
    return carregar_arquivo(Analise, EXEMPLOS / "analise_exemplo.yaml")


@pytest.fixture(scope="module")
def meta():
    return carregar_arquivo(Meta, EXEMPLOS / "meta_exemplo.yaml")


def test_exemplos_do_repositorio_sao_validos(analise, meta):
    assert analise.conclusao.resultado.value == "inconclusivo"
    assert meta.objetivo.quantidade_alvo == 100


def test_ida_e_volta_yaml_preserva_o_hash(analise, meta):
    for modelo, tipo, hash_ in ((analise, Analise, hash_documento), (meta, Meta, hash_contrato)):
        de_volta = carregar_texto(tipo, para_yaml(modelo), "yaml")
        assert de_volta == modelo and hash_(de_volta) == hash_(modelo)


def test_ida_e_volta_json_preserva_o_hash(analise, meta):
    for modelo, tipo, hash_ in ((analise, Analise, hash_documento), (meta, Meta, hash_contrato)):
        de_volta = carregar_texto(tipo, para_json(modelo), "json")
        assert de_volta == modelo and hash_(de_volta) == hash_(modelo)


def test_json_de_intercambio_usa_texto_para_decimais_e_datas(meta):
    dados = ler_json(para_json(meta))
    assert dados["recursos"]["orcamento"] == "1000"
    assert dados["objetivo"]["prazo"].endswith("Z")
    assert dados["objetivo"]["quantidade_alvo"] == "100"
