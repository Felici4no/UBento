"""Contexto da meta: ativo, moeda, mercado, conta, origem e fonte autorizada. Valem no núcleo, quando a conciliação conhece as metas.

- Incompatibilidade EXPLÍCITA (dado presente dos dois lados e diferente) nunca comprova: `divergente`, com o motivo.
- Contexto OBRIGATÓRIO ausente (a conta, de um dos lados) é "indeterminado": `nao_verificavel` com `contexto_indeterminado`; não conta e não contradiz.
- Fonte alternativa pode ser importada para comparação, mas não comprova: `nao_verificavel` com `fonte_nao_autorizada`.
- Sem `metas`, a conciliação se comporta como antes (o contexto é verificado pelo chamador).
"""

from datetime import timedelta
from decimal import Decimal

import pytest
from nucleo.avaliacao.fabrica import G

from ubento.nucleo.conciliacao import FonteAutorizada, PoliticaConciliacao
from ubento.nucleo.esquema import Meta

from .fabrica import AGORA, BASE, FONTE, comprovado, execucao, externo, rodar, status

META = Meta.model_validate(G.meta(conta="conta-a"))  # tokx / usd / bolsa-a / conta-a
META_SEM_CONTA = Meta.model_validate(G.meta(conta=None))
POLITICA = PoliticaConciliacao(
    janela_atraso_segundos=3600, tolerancia_horario_segundos=60, janela_candidatos_segundos=300,
    fontes_autorizadas=(FonteAutorizada(conta_id="conta-a", mercado_id="bolsa-a", fonte_id=FONTE),),
)


def ok(**extra):
    """Registro externo no contexto certo (conta-a, bolsa-a, usd, simulado, fonte autorizada)."""
    return externo(**{"conta_id": "conta-a", **extra})


def conciliar_ctx(execs, recs, meta=META, politica=POLITICA, **kw):
    return rodar(execs, recs, politica=politica, metas=[meta], **kw)


def motivos(r, id_="ex-1"):
    return {m.value for m in status(r, id_).motivos}


def test_contexto_certo_comprova():
    r = conciliar_ctx([execucao()], [ok()])
    assert status(r, "ex-1").status.value == "conciliada" and comprovado(r) == Decimal("9.95")
    assert r.metas_validadas == (META.id,)


def test_sem_metas_o_comportamento_antigo_e_preservado():
    r = rodar([execucao()], [externo()])
    assert status(r, "ex-1").status.value == "conciliada" and r.metas_validadas == ()


@pytest.mark.parametrize("execucao_kw,registro_kw,motivo", [
    ({"ativo_id": "eth"}, {"ativo_id": "eth", "taxas": (("eth", "0.05"),)}, "ativo_da_meta_diferente"),
    ({"moeda_cotacao_id": "eur"}, {"moeda_cotacao_id": "eur"}, "moeda_da_meta_diferente"),
    ({}, {"moeda_cotacao_id": "eur"}, "moeda_da_meta_diferente"),  # a execução não declara moeda; o registro diz eur
    ({}, {"mercado_id": "bolsa-z"}, "mercado_da_meta_diferente"),
    ({}, {"conta_id": "conta-z"}, "conta_da_meta_diferente"),
    ({"origem": "observado"}, {}, "origem_diferente"),  # execução real, evidência simulada
    ({}, {"origem": "observado"}, "origem_diferente"),  # execução simulada, evidência real
])
def test_incompatibilidade_explicita_nunca_comprova(execucao_kw, registro_kw, motivo):
    r = conciliar_ctx([execucao(**execucao_kw)], [ok(**registro_kw)])
    assert status(r, "ex-1").status.value == "divergente" and motivo in motivos(r)
    assert comprovado(r) == 0


def test_origem_real_com_evidencia_real_e_simulada_com_simulada_comprovam():
    real = conciliar_ctx([execucao(origem="observado")], [ok(origem="observado")])
    simulada = conciliar_ctx([execucao(origem="simulado")], [ok(origem="simulado")])
    assert status(real, "ex-1").status.value == status(simulada, "ex-1").status.value == "conciliada"


def test_ativo_da_execucao_diferente_da_meta_nao_comprova_nem_sem_evidencia():
    r = conciliar_ctx([execucao(ativo_id="eth", refs=())], [])
    assert status(r, "ex-1").status.value == "divergente" and "ativo_da_meta_diferente" in motivos(r)


@pytest.mark.parametrize("meta,registro_kw", [
    (META, {"conta_id": None}),  # a evidência não diz de que conta é
    (META_SEM_CONTA, {"conta_id": "conta-a"}),  # o contrato não diz a conta
    (META_SEM_CONTA, {"conta_id": None}),
])
def test_conta_ausente_deixa_indeterminado_com_motivo_claro(meta, registro_kw):
    politica = POLITICA
    r = conciliar_ctx([execucao()], [externo(**registro_kw)], meta=meta, politica=politica)
    assert status(r, "ex-1").status.value == "nao_verificavel" and "contexto_indeterminado" in motivos(r)
    assert comprovado(r) == 0


def test_explicito_vence_o_indeterminado():
    r = conciliar_ctx([execucao()], [externo(conta_id=None, mercado_id="bolsa-z")])  # mercado errado E conta desconhecida
    assert status(r, "ex-1").status.value == "divergente" and "mercado_da_meta_diferente" in motivos(r)


# -- fonte de comprovação autorizada ------------------------------------------------------------------------------------------------


def test_fonte_nao_autorizada_pode_ser_importada_mas_nao_comprova():
    alternativa = externo("linha-7", conta_id="conta-a", fonte_id="export-csv")
    r = conciliar_ctx([execucao(refs=({"fonte_id": "export-csv", "id_externo": "linha-7"},))], [alternativa])
    assert status(r, "ex-1").status.value == "nao_verificavel" and "fonte_nao_autorizada" in motivos(r)
    assert comprovado(r) == 0


def test_a_mesma_compra_por_duas_fontes_conta_so_pela_autorizada():
    """Não se unem operações por semelhança: a segunda fonte é só comparação e não soma."""
    autorizada = execucao("ex-1", refs=("fill-001",))
    alternativa = execucao("ex-2", refs=({"fonte_id": "export-csv", "id_externo": "linha-7"},))  # a mesma compra real, vista por outra fonte
    r = conciliar_ctx([autorizada, alternativa], [ok(), externo("linha-7", conta_id="conta-a", fonte_id="export-csv")])
    assert status(r, "ex-1").status.value == "conciliada" and status(r, "ex-2").status.value == "nao_verificavel"
    assert comprovado(r) == status(r, "ex-1").efeito_no_progresso  # só a autorizada contribui


def test_execucao_que_mistura_fontes_nao_comprova():
    mista = execucao(refs=("fill-001", {"fonte_id": "export-csv", "id_externo": "linha-7"}), bruta="10", taxa="0.05")
    r = conciliar_ctx([mista], [ok(), externo("linha-7", conta_id="conta-a", fonte_id="export-csv")])
    assert status(r, "ex-1").status.value == "nao_verificavel" and "fonte_nao_autorizada" in motivos(r)


def test_sem_fonte_autorizada_definida_para_o_contexto_nada_comprova():
    sem = PoliticaConciliacao(janela_atraso_segundos=3600, tolerancia_horario_segundos=60)
    outra_conta = PoliticaConciliacao(janela_atraso_segundos=3600, tolerancia_horario_segundos=60,
                                      fontes_autorizadas=(FonteAutorizada(conta_id="conta-z", mercado_id="bolsa-a", fonte_id=FONTE),))
    for politica in (sem, outra_conta):  # a autorização é por conta E mercado
        r = conciliar_ctx([execucao()], [ok()], politica=politica)
        assert status(r, "ex-1").status.value == "nao_verificavel" and "fonte_autorizada_nao_definida" in motivos(r)
        assert comprovado(r) == 0


def test_registro_de_fonte_nao_autorizada_sem_dono_nao_vira_orfao_bloqueante_da_meta():
    r = conciliar_ctx([execucao()], [ok(), externo("linha-9", conta_id="conta-a", fonte_id="export-csv")])
    assert status(r, "ex-1").status.value == "conciliada"
    assert any(o.fonte_id == "export-csv" for o in r.orfaos)  # aparece no relatório (comparação); o avaliador decide que não bloqueia


def test_relatorio_continua_funcao_pura_das_entradas():
    a = conciliar_ctx([execucao()], [ok()])
    b = conciliar_ctx([execucao()], [ok()])
    assert a.hash_saida == b.hash_saida and a.hash_entradas == b.hash_entradas
    assert a.hash_entradas != rodar([execucao()], [ok()], politica=POLITICA).hash_entradas  # as metas fazem parte das entradas
    assert AGORA - BASE == timedelta(hours=2)
