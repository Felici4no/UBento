"""Reimportação: identidade da operação, conteúdo financeiro e metadados de recebimento são coisas diferentes.

Mudar só QUANDO a evidência chegou (`recebido_em`) não é uma mudança da operação: não cria conflito nem reverte progresso.
Mudar quantidade, preço, taxa ou status continua sendo detectado. A primeira chegada é a que vale.
"""

from decimal import Decimal

import pytest

from ubento.nucleo.conciliacao import Motivo

from .fabrica import AGORA, BASE, comprovado, execucao, externo, rodar, status


def test_so_o_recebido_em_muda_continua_sendo_a_mesma_operacao():
    r = rodar([execucao()], [externo(recebido_min=0), externo(recebido_min=60)])  # a mesma operação, reimportada uma hora depois
    assert status(r, "ex-1").status.value == "conciliada" and comprovado(r) == Decimal("9.95")  # 10 brutos - 0,05 de taxa, uma vez só


def test_a_primeira_chegada_vale_e_a_reimportacao_so_e_anotada():
    primeira, reimportada = externo(recebido_min=0), externo(recebido_min=60)
    r = rodar([execucao()], [primeira, reimportada])
    resultado = status(r, "ex-1")
    assert Motivo.REGISTRO_EXTERNO_REIMPORTADO in resultado.motivos  # rastreável, mas não bloqueia
    assert Motivo.VERSAO_EXTERNA_CONFLITANTE not in resultado.motivos
    # antes de a reimportação existir, só a primeira chegada é visível: o resultado é o mesmo e sem anotação de reimportação
    cedo = rodar([execucao()], [primeira, reimportada], agora=BASE + (AGORA - BASE) / 4)
    assert status(cedo, "ex-1").status.value == "conciliada" and Motivo.REGISTRO_EXTERNO_REIMPORTADO not in status(cedo, "ex-1").motivos


def test_reimportacoes_identicas_em_qualquer_ordem_dao_o_mesmo_resultado():
    a, b, c = externo(recebido_min=0), externo(recebido_min=30), externo(recebido_min=90)
    r1 = rodar([execucao()], [a, b, c])
    r2 = rodar([execucao()], [c, a, b])
    assert comprovado(r1) == comprovado(r2) and status(r1, "ex-1").status.value == status(r2, "ex-1").status.value == "conciliada"
    assert r1.hash_saida == r2.hash_saida


def test_ordem_das_taxas_nao_e_conteudo():
    duas = (("tokx", "0.02"), ("usd", "0.10"))
    r = rodar([execucao(bruta="10", taxa="0.02", taxa_na_cotacao="0.10", moeda_cotacao_id="usd")], [externo(taxas=duas), externo(taxas=duas[::-1], recebido_min=60)])
    assert status(r, "ex-1").status.value == "conciliada"


@pytest.mark.parametrize("mudanca", [
    {"qtd": "11"}, {"preco": "9.6"}, {"taxas": (("tokx", "0.06"),)}, {"status": "pendente"}, {"status": "cancelado"}, {"minutos": 5},
])
def test_mudanca_real_com_a_mesma_versao_continua_sendo_conflito(mudanca):
    r = rodar([execucao()], [externo(), externo(recebido_min=60, **mudanca)])
    assert status(r, "ex-1").status.value == "revisao" and Motivo.VERSAO_EXTERNA_CONFLITANTE in status(r, "ex-1").motivos
    assert comprovado(r) == 0


def test_versao_maior_continua_sendo_correcao_e_vale_a_ultima():
    r = rodar([execucao(bruta="11", taxa="0.05")], [externo(), externo(versao=2, qtd="11", recebido_min=60)])
    assert status(r, "ex-1").status.value == "conciliada"
    assert Motivo.CORRIGIDO_EXTERNAMENTE in status(r, "ex-1").motivos
