"""Identidade de um registro externo: fonte + id (a conta é atributo), versões e reimportação."""

from __future__ import annotations

from decimal import Decimal

from test_correcao_vinculo import CENARIO, base
from ubento.metas import EvidenciaExterna
from ubento.nucleo.avaliacao.reproducao import carregar_reproducao_meta
from ubento.nucleo.conciliacao import conciliar
from ubento.nucleo.conciliacao.modelos import RegistroExterno

O = carregar_reproducao_meta(CENARIO)
EXEC = O.execucoes[0]  # declara a referência corretora-sim/fill-1
FILL1 = O.registros_externos[0]


def status(externos):
    r = conciliar([EXEC], externos, politica=O.politica_conciliacao, agora=O.momentos[-1].agora, coberturas_execucoes=O.coberturas_execucoes)
    return r.execucoes[0].status.value


def test_chave_e_fonte_mais_id_a_conta_nao_faz_parte_da_identidade():
    outra_conta = FILL1.model_copy(update={"conta_id": "conta-z"})
    outra_fonte = FILL1.model_copy(update={"fonte_id": "outra-fonte"})
    assert FILL1.chave == outra_conta.chave == ("corretora-sim", "fill-1")  # mesma compra, conta é só atributo
    assert outra_fonte.chave != FILL1.chave  # mesmo id em outra fonte é OUTRA operação


def test_reimportar_a_mesma_operacao_nao_duplica_e_reimportar_com_conteudo_diferente_vira_outra_entrada():
    sv, mid, *_ = base()  # já importou 3 registros
    antes = len(sv.repo.entradas(mid, "registros_externos", RegistroExterno))
    assert sv.importar_evidencia(mid, EvidenciaExterna(registros_externos=O.registros_externos)) == 0  # idêntico: nada novo
    assert len(sv.repo.entradas(mid, "registros_externos", RegistroExterno)) == antes
    assert sv.importar_evidencia(mid, EvidenciaExterna(registros_externos=(FILL1.model_copy(update={"versao": 2, "quantidade": Decimal("5")}),))) == 1
    assert len(sv.repo.entradas(mid, "registros_externos", RegistroExterno)) == antes + 1  # correção da fonte: versão nova, a antiga fica


def test_versao_maior_da_mesma_chave_e_correcao_e_vale_a_ultima():
    assert status([FILL1]) == "conciliada"
    corrigido = FILL1.model_copy(update={"versao": 2, "quantidade": Decimal("5")})  # a fonte corrigiu a quantidade
    assert status([FILL1, corrigido]) == status([corrigido]) != "conciliada"  # vale a v2; a v1 não "salva" a execução


def test_mesma_versao_com_conteudo_diferente_e_conflito_nao_comprova():
    conflitante = FILL1.model_copy(update={"conta_id": "conta-z"})  # mesma chave, mesma versão, outro conteúdo
    assert status([FILL1]) == "conciliada"
    assert status([FILL1, conflitante]) != "conciliada"
    assert status([FILL1, FILL1.model_copy()]) == "conciliada"  # cópia idêntica é só reimportação


def test_mesmo_id_em_outra_fonte_nao_interfere_na_execucao():
    outra_fonte = FILL1.model_copy(update={"fonte_id": "outra-fonte", "quantidade": Decimal("9")})
    assert status([FILL1, outra_fonte]) == "conciliada"
