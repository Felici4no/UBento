"""Garantias da primeira versão no avaliador: contexto da meta, fonte autorizada, orçamento como custo total e limites não avaliados."""

from datetime import UTC, datetime
from decimal import Decimal

import pytest

from ubento.nucleo.avaliacao import ErroDeAvaliacao, avaliar_meta
from ubento.nucleo.avaliacao.reproducao import ativacao_de
from ubento.nucleo.conciliacao import conciliar
from ubento.nucleo.esquema import Meta
from ubento.nucleo.regras import Snapshot

from .fabrica import G, montar, rodar, ultimo

HORAS = ["13:00:00"]


def progresso(execucoes, externos, **kw):
    return ultimo(rodar(execucoes, externos, HORAS, **kw)).progresso


def motivos_pendencia(p):
    return {m for pend in p.completude.pendencias for m in pend.motivos}


# -- contexto: ativo, origem, conta ---------------------------------------------------------------------------------------------------


def test_controle_execucao_no_contexto_certo_comprova_e_atinge():
    r = ultimo(rodar([G.ex("ex-1", "10", "0")], [G.ext("fill-1", "10")], HORAS))
    assert r.progresso.quantidade_comprovada == Decimal("10") and r.estado.value == "atingida"


def test_outro_ativo_nao_conta_para_a_meta_mesmo_com_evidencia_do_mesmo_outro_ativo():
    p = progresso([G.ex("ex-1", "10", "0", ativo_id="eth")], [G.ext("fill-1", "10", ativo="eth")])
    assert p.quantidade_comprovada == 0 and "ativo_da_meta_diferente" in motivos_pendencia(p)


def test_evidencia_simulada_nao_comprova_execucao_real_nem_o_inverso():
    real_com_simulada = progresso([G.ex("ex-1", "10", "0", origem="observado")], [G.ext("fill-1", "10", origem="simulado")])
    simulada_com_real = progresso([G.ex("ex-1", "10", "0", origem="simulado")], [G.ext("fill-1", "10", origem="observado")])
    assert real_com_simulada.quantidade_comprovada == simulada_com_real.quantidade_comprovada == 0
    assert "origem_diferente" in motivos_pendencia(real_com_simulada)


def test_conta_ou_mercado_explicitamente_diferentes_nao_comprovam():
    assert progresso([G.ex("ex-1", "10", "0")], [G.ext("fill-1", "10", conta="conta-b")]).quantidade_comprovada == 0
    assert progresso([G.ex("ex-1", "10", "0")], [G.ext("fill-1", "10", mercado="bolsa-b")]).quantidade_comprovada == 0


def test_conta_ausente_deixa_indeterminado_e_a_meta_nao_conclui():
    sem_conta_no_contrato = ultimo(rodar([G.ex("ex-1", "10", "0")], [G.ext("fill-1", "10")], HORAS, conta=None))
    sem_conta_na_evidencia = ultimo(rodar([G.ex("ex-1", "10", "0")], [G.ext("fill-1", "10", conta=None)], HORAS))
    for r in (sem_conta_no_contrato, sem_conta_na_evidencia):
        assert r.progresso.quantidade_comprovada == 0 and r.estado.value == "ativa"  # há prazo: não expira, só não comprova
        assert "contexto_indeterminado" in motivos_pendencia(r.progresso)
        assert r.progresso.completude.completa is False


# -- fonte autorizada ----------------------------------------------------------------------------------------------------------------------


def test_fonte_alternativa_importada_para_comparacao_nao_acrescenta_progresso():
    autorizada = G.ex("ex-1", "6", "0", h="10:00:00")
    alternativa = G.ex("ex-2", "4", "0", h="11:00:00", fonte="export-csv", refs=["linha-7"])  # outra fonte vendo uma compra
    p = progresso([autorizada, alternativa], [G.ext("fill-1", "6"), G.ext("linha-7", "4", h="11:00:00", fonte="export-csv")])
    assert p.quantidade_comprovada == Decimal("6")  # só a fonte autorizada comprova
    assert "fonte_nao_autorizada" in motivos_pendencia(p)


def test_registro_de_fonte_alternativa_sem_execucao_nao_bloqueia_a_meta():
    r = ultimo(rodar([G.ex("ex-1", "10", "0")], [G.ext("fill-1", "10"), G.ext("linha-9", "3", h="10:30:00", fonte="export-csv")], HORAS))
    assert r.estado.value == "atingida"
    orfao = next(o for o in r.progresso.orfaos if o.id_externo == "linha-9")
    assert orfao.relevante is False and "fonte_nao_autorizada" in {m.value for m in orfao.motivos}


def test_sem_fonte_autorizada_para_a_conta_e_o_mercado_nada_comprova():
    sem = {"janela_atraso_segundos": 3600, "tolerancia_horario_segundos": 60}
    p = progresso([G.ex("ex-1", "10", "0")], [G.ext("fill-1", "10")], politica_conciliacao=sem)
    assert p.quantidade_comprovada == 0 and "fonte_autorizada_nao_definida" in motivos_pendencia(p)


def test_o_avaliador_recusa_um_relatorio_que_nao_validou_o_contexto_da_meta():
    arquivo = montar([G.ex("ex-1", "10", "0")], [G.ext("fill-1", "10")], HORAS)
    sem_contexto = conciliar(arquivo.execucoes, arquivo.registros_externos, politica=arquivo.politica_conciliacao, agora=datetime(2026, 10, 20, 13, tzinfo=UTC))
    with pytest.raises(ErroDeAvaliacao, match="contexto"):
        avaliar_meta(arquivo.meta, ativacao_de(arquivo), [], [], sem_contexto, Snapshot(observacoes=()), datetime(2026, 10, 20, 13, tzinfo=UTC))
    assert isinstance(arquivo.meta, Meta)


# -- orçamento: custo total ------------------------------------------------------------------------------------------------------------------


def test_taxa_em_terceiro_ativo_sem_conversao_impede_declarar_o_orcamento_satisfeito():
    execucao = G.ex("ex-1", "10", "0", taxas_outros_ativos=[{"ativo_id": "bnb", "valor": "0.001"}])
    registro = G.ext("fill-1", "10", [("bnb", "0.001")])
    r = ultimo(rodar([execucao], [registro], HORAS))
    p = r.progresso
    assert p.quantidade_comprovada == Decimal("10")  # a quantidade está comprovada...
    assert p.orcamento.resultado.value == "indeterminado" and "taxa_em_terceiro_ativo_sem_conversao" in {m.value for m in p.orcamento.motivos}
    assert p.elegibilidade.resultado.value == "indeterminado" and r.estado.value == "ativa"  # ...mas a meta não se declara cumprida


def test_estouro_ja_demonstrado_continua_falso_mesmo_com_taxa_em_terceiro_ativo():
    execucao = G.ex("ex-1", "10", "0", taxas_outros_ativos=[{"ativo_id": "bnb", "valor": "0.001"}])  # 10 x 9,5 = 95 usd gastos
    registro = G.ext("fill-1", "10", [("bnb", "0.001")])
    p = progresso([execucao], [registro], orcamento="50")
    assert p.orcamento.resultado.value == "falso" and "orcamento_excedido" in {m.value for m in p.orcamento.motivos}
    assert p.elegibilidade.resultado.value == "falso"


def test_sem_taxa_em_terceiro_ativo_o_orcamento_cabe_e_e_verdadeiro():
    p = progresso([G.ex("ex-1", "10", "0")], [G.ext("fill-1", "10")])
    assert p.orcamento.resultado.value == "verdadeiro"


# -- limites do contrato ainda não avaliados ------------------------------------------------------------------------------------------------


def test_limite_de_exposicao_configurado_e_nao_implementado_nao_aparece_como_cumprido():
    r = ultimo(rodar([G.ex("ex-1", "10", "0")], [G.ext("fill-1", "10")], HORAS, exposicao="0.5"))
    p = r.progresso
    assert p.quantidade_comprovada == Decimal("10")
    assert p.limites_nao_avaliados == ("recursos.exposicao_maxima",)
    assert p.elegibilidade.resultado.value == "indeterminado" and "limite_nao_avaliado" in {m.value for m in p.elegibilidade.motivos}
    assert r.estado.value == "ativa"


def test_exposicao_total_significa_sem_limite_e_os_demais_campos_ficam_listados():
    p = progresso([G.ex("ex-1", "10", "0")], [G.ext("fill-1", "10")])
    assert p.limites_nao_avaliados == () and p.elegibilidade.resultado.value == "verdadeiro"
    assert set(p.campos_nao_avaliados) == {
        "recursos.exposicao_maxima", "recursos.saldo_reservado", "custos.custo_fixo", "custos.taxa_proporcional", "custos.tratamento_taxa",
    }
