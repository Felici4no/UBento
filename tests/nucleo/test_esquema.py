from copy import deepcopy
from decimal import Decimal
from pathlib import Path

import pytest

from ubento.nucleo.carregador import ErroDeValidacao, carregar_arquivo, ler_yaml, validar
from ubento.nucleo.esquema import (
    Analise, Ativo, Cenario, Evento, Execucao, Meta, Observacao, Politicas, ids_da_condicao,
)

EXEMPLOS = Path(__file__).resolve().parents[2] / "exemplos" / "nucleo"
H = "a" * 64


@pytest.fixture
def analise_dados():
    return ler_yaml((EXEMPLOS / "analise_exemplo.yaml").read_text(encoding="utf-8"))


@pytest.fixture
def meta_dados():
    return ler_yaml((EXEMPLOS / "meta_exemplo.yaml").read_text(encoding="utf-8"))


def recusa(modelo, dados, trecho=None):
    with pytest.raises(ErroDeValidacao) as erro:
        validar(modelo, dados)
    if trecho:
        assert trecho in str(erro.value)
    return erro.value


# -- exemplos ------------------------------------------------------------------------------------


def test_exemplos_validam():
    carregar_arquivo(Analise, EXEMPLOS / "analise_exemplo.yaml")
    carregar_arquivo(Meta, EXEMPLOS / "meta_exemplo.yaml")


def test_modelos_sao_imutaveis(analise_dados):
    analise = validar(Analise, analise_dados)
    with pytest.raises(Exception):
        analise.versao = 2


@pytest.mark.parametrize("modelo, chave", [(Analise, "analise_dados"), (Meta, "meta_dados")])
def test_campo_desconhecido_e_erro(request, modelo, chave):
    dados = request.getfixturevalue(chave)
    dados["campo_inventado"] = 1
    recusa(modelo, dados, "campo_inventado")


# -- observação: ausência exige motivo ------------------------------------------------------------------------


def _obs(**extra):
    base = dict(id="o1", ativo_id="tokx", metrica_id="m", fonte_id="f", mercado_id="b", unidade="USD", valor="1",
                qualidade="disponivel", origem="simulado", observado_em="2026-01-01T00:00:00Z", coletado_em="2026-01-01T00:00:01Z")
    return {**base, **extra}


def test_observacao_valida():
    assert Observacao(**_obs()).valor == Decimal(1)


@pytest.mark.parametrize("extra, trecho", [
    ({"valor": None}, "precisa de valor"),
    ({"valor": None, "qualidade": "ausente"}, "motivo_ausencia"),
    ({"qualidade": "divergente"}, "motivo_ausencia"),
    ({"valor": None, "qualidade": "disponivel", "motivo_ausencia": "x"}, "precisa de valor"),
    ({"coletado_em": "2025-12-31T00:00:00Z"}, "anterior"),
    ({"periodo_inicio": "2026-01-01T00:00:00Z"}, "juntos"),
    ({"periodo_inicio": "2026-01-02T00:00:00Z", "periodo_fim": "2026-01-01T00:00:00Z"}, "anterior"),
    ({"valor": 1.5}, "texto decimal"),
    ({"observado_em": "2026-01-01T00:00:00"}, "fuso"),
    ({"origem": "real"}, "origem"),
])
def test_observacao_invalida(extra, trecho):
    recusa(Observacao, _obs(**extra), trecho)


def test_observacao_ausente_com_motivo_e_aceita():
    o = Observacao(**_obs(valor=None, qualidade="ausente", motivo_ausencia="fonte offline"))
    assert o.valor is None


# -- ativo -------------------------------------------------------------------------------------------------------


def test_ativo_token_exige_contrato():
    base = dict(id="tokx", simbolo="TOKX", rede="rede-a", tipo="token", casas_decimais=6, incremento_quantidade="0.01")
    recusa(Ativo, base, "contrato")
    assert Ativo(**base, contrato="0xabc").contrato == "0xabc"
    recusa(Ativo, {**base, "tipo": "nativo", "contrato": "0xabc"}, "só token")


# -- análise ------------------------------------------------------------------------------------------------------


def test_fato_sem_referencia_e_recusado(analise_dados):
    analise_dados["afirmacoes"][0]["referencias"] = []
    recusa(Analise, analise_dados, "exige ao menos uma referência")


def test_referencia_inexistente_e_recusada(analise_dados):
    analise_dados["afirmacoes"][1]["referencias"] = ["obs-inexistente"]
    recusa(Analise, analise_dados, "referências inválidas")


def test_calculo_nao_pode_apontar_para_observacao(analise_dados):
    analise_dados["afirmacoes"][1]["referencias"] = ["obs-preco-001"]
    recusa(Analise, analise_dados, "referências inválidas")


def test_indicador_com_observacao_inexistente(analise_dados):
    analise_dados["indicadores"][0]["entradas"] = ["nao-existe"]
    recusa(Analise, analise_dados, "inexistentes")


def test_ids_repetidos(analise_dados):
    analise_dados["observacoes"].append(deepcopy(analise_dados["observacoes"][0]))
    recusa(Analise, analise_dados, "repetidos")


def test_indicador_indisponivel_exige_motivo(analise_dados):
    analise_dados["indicadores"][0]["resultado"] = None
    recusa(Analise, analise_dados, "motivo_indisponivel")


def test_probabilidade_exige_metodo(analise_dados):
    analise_dados["cenarios"][0]["probabilidade"] = "0.3"
    recusa(Analise, analise_dados, "metodo_estimacao")
    analise_dados["cenarios"][0]["metodo_estimacao"] = "Frequência histórica de 2020 a 2025, documento X."
    assert validar(Analise, analise_dados).cenarios[0].probabilidade == Decimal("0.3")


def test_cenario_sem_premissas_e_recusado(analise_dados):
    analise_dados["cenarios"][0]["premissas"] = []
    recusa(Analise, analise_dados)


def test_evidencia_precisa_de_origem(analise_dados):
    del analise_dados["evidencias"][0]["referencia"]
    recusa(Analise, analise_dados, "referencia ou conteudo_hash")


def test_ativos_do_escopo_sao_conjunto(analise_dados):
    analise_dados["escopo"]["ativos"] = ["b", "a", "b"]
    assert validar(Analise, analise_dados).escopo.ativos == ("a", "b")


def test_dois_cenarios_com_mesmo_nome(analise_dados):
    analise_dados["cenarios"][1]["nome"] = "adverso"
    recusa(Analise, analise_dados, "mesmo nome")


# -- meta -------------------------------------------------------------------------------------------------------------------


def test_prazo_deve_ser_posterior_a_criacao(meta_dados):
    meta_dados["objetivo"]["prazo"] = "2026-10-18T13:30:00-03:00"
    recusa(Meta, meta_dados, "posterior")


def test_reserva_nao_pode_superar_orcamento(meta_dados):
    meta_dados["recursos"]["saldo_reservado"] = "1000.01"
    recusa(Meta, meta_dados, "saldo_reservado")


def test_taxa_e_exposicao_sao_fracoes(meta_dados):
    meta_dados["custos"]["taxa_proporcional"] = "5"
    recusa(Meta, meta_dados, "entre 0 e 1")
    meta_dados["custos"]["taxa_proporcional"] = "0.005"
    meta_dados["recursos"]["exposicao_maxima"] = "1.5"
    recusa(Meta, meta_dados, "entre 0 e 1")


@pytest.mark.parametrize("grupo", ["bloqueios", "entrada", "invalidacao"])
def test_regras_obrigatorias_nao_podem_ser_vazias(meta_dados, grupo):
    meta_dados["regras"][grupo] = []
    recusa(Meta, meta_dados)


def test_composicoes_nao_podem_ter_lista_vazia(meta_dados):
    meta_dados["regras"]["entrada"] = [{"id": "x", "op": "all", "itens": []}]
    recusa(Meta, meta_dados)


def test_ids_de_condicao_repetidos(meta_dados):
    meta_dados["regras"]["invalidacao"][0]["id"] = "en-preco"
    recusa(Meta, meta_dados, "repetidos")


def test_operador_desconhecido(meta_dados):
    meta_dados["regras"]["entrada"][0]["op"] = "eval"
    recusa(Meta, meta_dados)


def test_condicoes_aninhadas_e_percurso_de_ids(meta_dados):
    meta_dados["regras"]["entrada"] = [{
        "id": "e1", "op": "all", "itens": [
            meta_dados["regras"]["entrada"][0],
            {"id": "e2", "op": "not", "item": {"id": "e3", "op": "any", "itens": [meta_dados["regras"]["invalidacao"].pop()]}},
        ],
    }]
    meta_dados["regras"]["invalidacao"] = [{
        "id": "i9", "op": "lt", "esquerda": {"tipo": "valor", "valor": "1", "unidade": "razao"},
        "direita": {"tipo": "valor", "valor": "2", "unidade": "razao"},
    }]
    meta = validar(Meta, meta_dados)
    assert ids_da_condicao(meta.regras.entrada[0]) == ["e1", "en-preco", "e2", "e3", "inv-queda"]


def test_operando_precisa_de_tipo_valido(meta_dados):
    meta_dados["regras"]["entrada"][0]["direita"] = {"tipo": "codigo", "valor": "__import__('os')"}
    recusa(Meta, meta_dados)


def test_ordem_de_empate_deve_ser_permutacao():
    Politicas(carencia_dados_segundos=0, ordem_empate=("entrada", "expirada", "invalidada", "atingida"))
    with pytest.raises(Exception):
        Politicas(carencia_dados_segundos=0, ordem_empate=("atingida", "atingida", "expirada", "entrada"))
    with pytest.raises(Exception):
        Politicas(carencia_dados_segundos=0, ordem_empate=("atingida", "invalidada", "expirada"))


def test_tolerancia_unica_por_metrica_e_mercado(meta_dados):
    meta_dados["politicas"]["tolerancias"].append(deepcopy(meta_dados["politicas"]["tolerancias"][0]))
    recusa(Meta, meta_dados, "repetida")


def test_meta_nao_substitui_a_si_mesma(meta_dados):
    meta_dados["substitui_meta_id"] = meta_dados["id"]
    recusa(Meta, meta_dados, "si mesma")


def test_so_acumular_quantidade_na_v1(meta_dados):
    meta_dados["objetivo"]["tipo"] = "atingir_valor_liquido"
    recusa(Meta, meta_dados)


def test_aprovacao_exige_justificativa_substancial(meta_dados):
    meta_dados["fundamentacao"]["aprovacoes"][0]["justificativa"] = "ok"
    recusa(Meta, meta_dados)


def test_hash_malformado_e_recusado(meta_dados):
    meta_dados["analise_hash"] = "XYZ"
    recusa(Meta, meta_dados)


# -- execução e evento --------------------------------------------------------------------------------------------------------------------


def _exec(**extra):
    base = dict(id="ex1", meta_id="m1", ativo_id="tokx", lado="compra", quantidade_bruta="10", taxa_no_ativo="0.05",
                quantidade_liquida="9.95", preco_executado="9.5", executada_em="2026-10-20T10:00:00Z",
                confirmada_em="2026-10-20T10:00:05Z", fonte_id="f", origem="simulado")
    return {**base, **extra}


def test_execucao_liquida_e_bruta_menos_taxa_no_ativo():
    assert Execucao(**_exec()).quantidade_liquida == Decimal("9.95")
    recusa(Execucao, _exec(quantidade_liquida="10"), "quantidade_liquida")


def test_estorno_exige_referencia_e_so_ele_pode_ter():
    recusa(Execucao, _exec(lado="estorno_compra"), "estorna_execucao_id")
    recusa(Execucao, _exec(estorna_execucao_id="ex0"), "estorna_execucao_id")
    assert Execucao(**_exec(lado="estorno_compra", estorna_execucao_id="ex0")).lado.value == "estorno_compra"


def test_execucao_so_existe_depois_de_confirmada():
    recusa(Execucao, _exec(confirmada_em="2026-10-20T09:00:00Z"), "anterior")
    dados = _exec()
    del dados["confirmada_em"]
    recusa(Execucao, dados, "confirmada_em")


def _evento(**extra):
    base = dict(id="ev1", meta_id="m1", sequencia=1, tipo="avaliada", horario_evidencia="2026-10-20T10:00:00Z", registrado_em="2026-10-20T10:00:01Z")
    return {**base, **extra}


def test_eventos():
    assert Evento(**_evento()).sequencia == 1
    recusa(Evento, _evento(sequencia=0))
    recusa(Evento, _evento(registrado_em="2026-10-20T09:00:00Z"), "anterior")
    recusa(Evento, _evento(tipo="reconciliada"), "autor")
    recusa(Evento, _evento(tipo="reconciliada", autor="Fulano"), "motivo")
    recusa(Evento, _evento(tipo="alerta_emitido"), "chave_idempotencia")
    assert Evento(**_evento(tipo="alerta_emitido", chave_idempotencia=H)).tipo.value == "alerta_emitido"
    recusa(Evento, _evento(tipo="cancelada"), "autor")


def test_cenario_adverso_referencia_favoravel_sao_os_nomes_validos():
    for nome in ("adverso", "referencia", "favoravel"):
        Cenario(id="c", nome=nome, horizonte_dias=30, premissas=["x"])
    recusa(Cenario, dict(id="c", nome="otimista", horizonte_dias=30, premissas=["x"]))
