"""Regras padrão de gestão de risco (caixas de seleção): risco por operação, stop diário, meta diária e tamanho da posição pela fórmula.

Conta de teste: US$ 10.000 em caixa. Risco 1% = US$ 100 por operação. Stop-loss de 8% → tamanho = 100 / 0,08 = US$ 1.250 (as contas estão nos comentários).
"""

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from datetime import datetime, timedelta  # noqa: E402

import pytest  # noqa: E402

from ubento import engine  # noqa: E402
from ubento.agent_config import AgentConfig, describe  # noqa: E402
from ubento.store import Decision, Store  # noqa: E402
from ubento.workspace import Workspace  # noqa: E402

AGORA = datetime(2026, 10, 19, 14, 0, 0)


@pytest.fixture
def store():
    s = Store(now=AGORA)
    s.holdings = {"USD": 10_000.0}
    s.cost_basis, s.decisions = {}, []
    return s


def cfg(**extra):
    base = dict(strategy="dca", rule_risk=True, rule_risk_pct=1.0, stop_loss_pct=8, reserve_pct=20, max_position_pct=40)
    return AgentConfig(**{**base, **extra}).validated()


def compra(usd=3000.0, simbolo="ETH"):
    return engine._buy(simbolo, usd, "Compra recorrente", AGORA)


def venda(usd=500.0):
    return engine._sell("ETH", usd, "Realizou lucro", AGORA)


def resultado(store, pnl, quando=AGORA, status="executed"):
    store.decisions.append(Decision("sell", "Vendeu", "x", "", quando, status=status, pnl_usd=pnl, value_usd=100.0))


# -- risco por operação e tamanho pela fórmula ----------------------------------------------------------------------------------------


def test_compra_maior_que_o_risco_e_reduzida_ao_tamanho_da_formula(store):
    (d,) = engine._aplicar_regras(cfg(), store, [compra(3000.0)], AGORA)
    assert (d.trade.usd, d.trade.fee, d.value_usd) == (1250.0, 1.25, 1250.0)  # 1% de 10.000 = 100 de risco; 100 / 8% = 1.250
    assert "risco de 1%" in d.detail and "1.250,00" in d.detail and "3.000,00" in d.detail  # a decisão explica o ajuste
    assert d.trade.qty * engine.ASSETS["ETH"].price == pytest.approx(1248.75, abs=0.02)


def test_risco_de_meio_por_cento_corta_pela_metade(store):
    (d,) = engine._aplicar_regras(cfg(rule_risk_pct=0.5), store, [compra(3000.0)], AGORA)
    assert d.trade.usd == 625.0  # 50 / 0,08


def test_compra_menor_que_o_risco_nao_e_aumentada_sem_a_regra_de_tamanho(store):
    original = compra(500.0)
    (d,) = engine._aplicar_regras(cfg(), store, [original], AGORA)
    assert d is original


def test_regra_de_tamanho_usa_a_formula_mesmo_quando_a_estrategia_pediria_menos(store):
    (d,) = engine._aplicar_regras(cfg(rule_sizing=True), store, [compra(500.0)], AGORA)
    assert d.trade.usd == 1250.0


def test_tamanho_pela_formula_nunca_passa_do_caixa_disponivel(store):
    store.holdings = {"USD": 500.0, "ETH": 9500.0 / engine.ASSETS["ETH"].price}  # conta de 10.000, mas só 500 em caixa
    (d,) = engine._aplicar_regras(cfg(rule_sizing=True, reserve_pct=0), store, [compra(300.0, "SOL")], AGORA)
    assert d.trade.usd == 500.0  # a fórmula pediria 1.250


def test_caixa_dividido_entre_varias_compras_do_mesmo_lote(store):
    # gastável: 10.000 − 60% de reserva = 4.000. Três compras de 1.250 cabem (3.750); a quarta recebe só os 250 que sobram
    lote = [compra(300.0, s) for s in ("ETH", "SOL", "BNB", "AVAX")]
    out = engine._aplicar_regras(cfg(rule_sizing=True, reserve_pct=60, max_position_pct=100), store, lote, AGORA)
    assert [d.trade.usd for d in out] == [1250.0, 1250.0, 1250.0, 250.0]


def test_tamanho_pela_formula_respeita_a_posicao_maxima_por_ativo(store):
    (d,) = engine._aplicar_regras(cfg(rule_sizing=True, max_position_pct=10), store, [compra(300.0)], AGORA)
    assert d.trade.usd == 1000.0  # 10% de 10.000 = teto por ativo, menor que os 1.250 da fórmula


def test_compra_que_ficaria_abaixo_do_minimo_some(store):
    pequeno = Store(now=AGORA)
    pequeno.holdings, pequeno.cost_basis, pequeno.decisions = {"USD": 50.0}, {}, []
    (hold,) = engine._aplicar_regras(cfg(), pequeno, [compra(40.0)], AGORA)  # 1% de 50 = 0,50 de risco; 0,50 / 8% = 6,25: abaixo do mínimo de US$ 10
    assert hold.kind == "hold" and "mínimo" in hold.detail


def test_vendas_nunca_sao_reduzidas(store):
    store.holdings = {"USD": 0.0, "ETH": 5.0}
    original = venda(9000.0)
    assert engine._aplicar_regras(cfg(), store, [original], AGORA) == [original]


# -- stop diário e meta diária -----------------------------------------------------------------------------------------------------------


def test_stop_diario_bloqueia_compras_no_limite_e_deixa_as_vendas(store):
    resultado(store, -200.0)  # 2 × (1% de 10.000) = 200
    regras = cfg(rule_daily_stop=True, rule_daily_stop_x=2)
    out = engine._aplicar_regras(regras, store, [compra(500.0), venda(300.0)], AGORA)
    assert [d.kind for d in out] == ["sell"]  # reduzir risco continua permitido
    (hold,) = engine._aplicar_regras(regras, store, [compra(500.0)], AGORA)
    assert hold.kind == "hold" and "Stop diário atingido" in hold.detail and "−US$ 200,00" in hold.detail


def test_um_centavo_antes_do_stop_ainda_compra(store):
    resultado(store, -199.99)
    (d,) = engine._aplicar_regras(cfg(rule_daily_stop=True), store, [compra(500.0)], AGORA)
    assert d.kind == "buy"


def test_stop_de_tres_vezes_o_risco(store):
    resultado(store, -250.0)
    assert engine._aplicar_regras(cfg(rule_daily_stop=True, rule_daily_stop_x=3), store, [compra(500.0)], AGORA)[0].kind == "buy"  # limite 300
    resultado(store, -50.0)
    assert engine._aplicar_regras(cfg(rule_daily_stop=True, rule_daily_stop_x=3), store, [compra(500.0)], AGORA)[0].kind == "hold"  # −300


def test_meta_diaria_para_de_comprar_para_nao_devolver_o_lucro(store):
    resultado(store, 300.0)  # 3 × 100
    (hold,) = engine._aplicar_regras(cfg(rule_daily_goal=True, rule_daily_goal_x=3), store, [compra(500.0)], AGORA)
    assert hold.kind == "hold" and "Meta diária atingida" in hold.detail and "+US$ 300,00" in hold.detail
    store.decisions.clear()
    resultado(store, 299.99)
    assert engine._aplicar_regras(cfg(rule_daily_goal=True), store, [compra(500.0)], AGORA)[0].kind == "buy"


def test_o_resultado_do_dia_so_conta_o_que_foi_executado_hoje(store):
    resultado(store, -150.0)
    resultado(store, -999.0, quando=AGORA - timedelta(days=1))  # ontem: não conta
    resultado(store, -999.0, status="proposed")  # proposta: não conta
    store.decisions.append(Decision("hold", "Manteve", "x", "", AGORA))  # sem dinheiro: não conta
    resultado(store, 20.0)
    assert store.resultado_do_dia(AGORA.date()) == pytest.approx(-130.0)


def test_sem_a_caixa_de_risco_nada_muda_mesmo_com_as_outras_marcadas(store):
    original = [compra(3000.0)]
    c = cfg(rule_risk=False, rule_daily_stop=True, rule_daily_goal=True, rule_sizing=True).validated()
    assert not (c.rule_daily_stop or c.rule_daily_goal or c.rule_sizing)  # dependem do risco por operação
    assert engine._aplicar_regras(c, store, original, AGORA) is original


# -- configuração ------------------------------------------------------------------------------------------------------------------------


def test_valores_fora_do_permitido_voltam_ao_padrao():
    c = AgentConfig(rule_risk=True, rule_risk_pct=3.0, rule_daily_stop=True, rule_daily_stop_x=9, rule_daily_goal=True, rule_daily_goal_x=1).validated()
    assert (c.rule_risk_pct, c.rule_daily_stop_x, c.rule_daily_goal_x) == (1.0, 2, 3)
    assert AgentConfig(rule_risk=True, rule_risk_pct=0.75).validated().rule_risk_pct == 0.75


def test_configuracao_antiga_sem_as_regras_continua_valida():
    c = AgentConfig.from_dict({"strategy": "dca", "risk": 2})
    assert not (c.rule_risk or c.rule_daily_stop or c.rule_daily_goal or c.rule_sizing)


def test_stop_loss_aparece_para_qualquer_estrategia_quando_o_risco_esta_ligado():
    assert not AgentConfig(strategy="dca").relevant("stop_loss_pct")
    assert AgentConfig(strategy="dca", rule_risk=True).relevant("stop_loss_pct")
    assert not AgentConfig(strategy="manual", rule_risk=True).relevant("stop_loss_pct")


def test_o_resumo_do_agente_cita_as_regras():
    texto = describe(cfg(rule_daily_stop=True, rule_daily_goal=True, rule_daily_goal_x=4, rule_sizing=True))
    assert "risco de 1% da conta por operação" in texto and "para de comprar ao perder 2× o risco" in texto
    assert "para de comprar ao ganhar 4× o risco" in texto and "tamanho pela fórmula" in texto
    assert "regras de risco" not in describe(AgentConfig(strategy="dca")).lower()


# -- de ponta a ponta --------------------------------------------------------------------------------------------------------------------


def test_o_agente_roda_com_as_regras_e_a_decisao_executada_respeita_o_risco():
    ws = Workspace()
    agente = ws.agents[0]
    agente.store.holdings, agente.store.cost_basis, agente.store.decisions = {"USD": 10_000.0}, {}, []
    ws.set_config(agente.id, strategy="dca", mode="auto", rule_risk=True, rule_risk_pct=1.0, stop_loss_pct=8, rule_sizing=True, reserve_pct=20, trade_size_pct=25)
    feitas, _ = ws.run_agent(agente.id, AGORA)
    (d,) = agente.store.decisions
    assert feitas == 1 and d.value_usd == 1250.0 and d.status == "executed"  # a estratégia queria 2.000 (25% de 8.000); o risco manda 1.250
    assert agente.store.holdings["USD"] == 8750.0
    # a segunda rodada já enxerga o resultado do dia (−1,25 de taxa): ainda longe do stop de 200
    assert ws.run_agent(agente.id, AGORA + timedelta(minutes=5))[0] == 1


# -- caixas de seleção na tela -----------------------------------------------------------------------------------------------------------


@pytest.fixture(scope="module")
def app():
    from PySide6.QtWidgets import QApplication

    from ubento.ui import theme

    a = QApplication.instance() or QApplication([])
    a.setStyleSheet(theme.APP_QSS)
    return a


def pagina(app):
    from ubento.ui.agent_page import AgentConfigPage

    ws = Workspace()
    return ws, AgentConfigPage(ws, ws.agents[0].id)


def test_as_quatro_caixas_comecam_desmarcadas_e_so_o_risco_esta_liberado(app):
    ws, page = pagina(app)
    assert set(page.rule_boxes) == {"risk", "stop", "goal", "sizing"}
    assert not any(b.isChecked() for b in page.rule_boxes.values())
    assert page.rule_boxes["risk"].isEnabled() and not any(page.rule_boxes[k].isEnabled() for k in ("stop", "goal", "sizing"))


def test_marcar_o_risco_libera_as_outras_e_grava_na_configuracao(app):
    ws, page = pagina(app)
    page.rule_boxes["risk"].setChecked(True)
    assert ws.agents[0].config.rule_risk and all(page.rule_boxes[k].isEnabled() for k in ("stop", "goal", "sizing"))
    page.rule_boxes["stop"].setChecked(True)
    page.rule_pills["stop"]["buttons"][3].click()
    page.rule_pills["risk"]["buttons"][0.5].click()
    cfg = ws.agents[0].config
    assert (cfg.rule_daily_stop, cfg.rule_daily_stop_x, cfg.rule_risk_pct) == (True, 3, 0.5)
    assert page.rule_pills["stop"]["buttons"][3].isChecked() and not page.rule_pills["stop"]["buttons"][2].isChecked()


def test_desmarcar_o_risco_desliga_as_dependentes_na_tela_tambem(app):
    ws, page = pagina(app)
    page.rule_boxes["risk"].setChecked(True)
    page.rule_boxes["goal"].setChecked(True)
    page.rule_boxes["sizing"].setChecked(True)
    page.rule_boxes["risk"].setChecked(False)
    cfg = ws.agents[0].config
    assert not (cfg.rule_risk or cfg.rule_daily_goal or cfg.rule_sizing)
    assert not any(b.isChecked() for b in page.rule_boxes.values()) and not page.rule_boxes["goal"].isEnabled()
    assert not any(botao.isEnabled() for botao in page.rule_pills["goal"]["buttons"].values())  # sem a caixa, os valores ficam travados


def test_pacote_padrao_marca_tudo_com_valores_moderados(app):
    ws, page = pagina(app)
    page.rules_pack.click()
    cfg = ws.agents[0].config
    assert (cfg.rule_risk, cfg.rule_risk_pct, cfg.rule_daily_stop, cfg.rule_daily_stop_x, cfg.rule_daily_goal, cfg.rule_daily_goal_x, cfg.rule_sizing) == (True, 0.75, True, 2, True, 3, True)
    assert all(b.isChecked() for b in page.rule_boxes.values())
    assert "risco de 0,75%" in page.summary.text()


def test_stop_loss_vira_visivel_com_o_risco_ligado_e_a_secao_some_no_manual(app):
    ws, page = pagina(app)
    ws.set_config(ws.agents[0].id, strategy="dca")
    assert page.param_rows["stop_loss_pct"].isHidden()
    page.rule_boxes["risk"].setChecked(True)
    assert not page.param_rows["stop_loss_pct"].isHidden()  # a distância do stop é a base da conta
    ws.set_config(ws.agents[0].id, strategy="manual")
    assert page.sections["rules"].isHidden()


def test_caixa_marcada_desenha_a_marca_de_verificacao(app):
    from ubento.ui.controls import CheckBox

    caixa = CheckBox()
    caixa.setChecked(True)
    azul = caixa.grab().toImage()
    caixa.setChecked(False)
    vazia = caixa.grab().toImage()
    assert azul != vazia
    assert azul.pixelColor(6, 13).red() < 100 and azul.pixelColor(6, 13).blue() > 200  # preenchida de azul
    assert sum(1 for x in range(8, 19) for y in range(8, 19) if azul.pixelColor(x, y).red() > 220) >= 6  # com a marca branca no meio
    assert vazia.pixelColor(6, 13).red() > 200  # vazia: sem preenchimento
