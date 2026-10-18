import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from ubento.workspace import Workspace  # noqa: E402
from ubento.ui import theme  # noqa: E402
from ubento.ui.main_window import MainWindow  # noqa: E402


@pytest.fixture(scope="module")
def app():
    a = QApplication.instance() or QApplication([])
    a.setStyleSheet(theme.APP_QSS)
    return a


@pytest.fixture
def window(app):
    w = MainWindow(Workspace(), animations=False)
    w.show()
    app.processEvents()
    yield w
    w.close()


def test_exchange_button_runs_the_swap(window):
    window.select(window.workspace.agents[0].id)
    dash = window.dashboard(window.current)
    ex, store = dash.exchange, dash.store
    usd = store.holdings["USD"]
    ex.send_panel.input.setText("500")
    assert ex.button._reason is None
    ex._submit()
    assert store.holdings["USD"] == pytest.approx(usd - 500)
    assert store.decisions[0].title == "Swap USD → ETH"


def test_exchange_blocks_invalid_amount(window):
    ex = window.dashboard(window.workspace.agents[0].id).exchange
    ex.send_panel.input.setText("99999999")
    assert ex.button._reason == "Saldo insuficiente"
    ex.send_panel.input.setText("")
    assert ex.button._reason == "Informe um valor"


def test_swap_button_inverts_sides(window):
    ex = window.dashboard(window.workspace.agents[0].id).exchange
    ex.swap_sides()
    assert (ex.send, ex.receive) == ("ETH", "USD")


def test_picking_the_other_side_currency_inverts(window):
    ex = window.dashboard(window.workspace.agents[0].id).exchange
    ex._pick("send", "ETH")
    assert (ex.send, ex.receive) == ("ETH", "USD")


def test_range_change_updates_chart_and_total(window):
    card = window.dashboard('overview').total
    card.set_range("1A")
    assert len(card.chart._points) == 52
    card.set_range("1S")
    assert len(card.chart._points) == 7


def test_buy_usdc_shortcut_prefills_exchange(window):
    dash = window.dashboard(window.workspace.agents[0].id)
    dash.coin.buy_clicked.emit()
    assert (dash.exchange.send, dash.exchange.receive) == ("USD", "USDC")


def test_overview_is_readonly_and_sums_agents(window):
    ws = window.workspace
    overview = ws.overview
    assert overview.validate("USD", "ETH", 10) == "Escolha um agente para fazer swap"
    assert overview.holdings["USD"] == pytest.approx(sum(a.store.holdings["USD"] for a in ws.agents))


def test_swap_in_an_agent_updates_overview(window):
    ws = window.workspace
    agent = ws.agents[0]
    before = ws.overview.holdings["USD"]
    assert agent.store.execute("USD", "ETH", 500) is None
    assert ws.overview.holdings["USD"] == pytest.approx(before - 500)


def test_tabs_follow_workspace_changes(window):
    ws = window.workspace
    n = len(ws.agents)
    new = ws.add("Teste")
    assert new.id in window.pages and len(window.header._tabs) == n + 2
    ws.rename(new.id, "Outro")
    assert window.header._tabs[-1].name == "Outro"
    ws.move_to(new.id, 0)
    assert window.header._tabs[1].key == new.id
    window.select(new.id)
    ws.remove(new.id)
    assert window.current == "overview" and new.id not in window.pages


def test_context_menu_contents(window):
    labels = lambda m: [a.text() for a in m.actions() if a.text()]  # noqa: E731
    assert labels(window.build_menu(None)) == ["Novo agente"]
    assert labels(window.build_menu("overview")) == ["Renomear…"]
    agent_menu = labels(window.build_menu(window.workspace.agents[0].id))
    assert agent_menu == ["Configurar agente…", "Metas…", "Renomear…", "Cor", "Duplicar", "Mover para a esquerda", "Mover para a direita", "Remover"]


def test_overview_swaps_agents_card_for_exchange(window):
    overview = window.dashboard("overview")
    assert overview.exchange is None and overview.agents is not None
    assert window.dashboard(window.workspace.agents[0].id).agents is None


def test_agents_card_rows_and_range_link(window):
    overview = window.dashboard("overview")
    rows = overview.agents.list.rows()
    assert [r["name"] for r in rows] == [a.name for a in window.workspace.agents]
    assert sum(r["share"] for r in rows) == pytest.approx(1.0)
    overview.total.set_range("1A")
    assert overview.agents.list.range_key == "1A"


def test_clicking_an_agent_opens_its_tab(window):
    target = window.workspace.agents[1]
    window.dashboard("overview").agents.agent_clicked.emit(target.id)
    assert window.current == target.id


def test_overview_decisions_carry_the_agent(window):
    ws = window.workspace
    decisions = ws.overview.decisions
    assert decisions and all(d.agent in {a.id for a in ws.agents} for d in decisions)
    assert decisions == sorted(decisions, key=lambda d: d.moment, reverse=True)


def test_header_eye_and_gear(window):
    from ubento import formatting

    ws = window.workspace
    try:
        window.header.privacy_toggled.emit()
        assert ws.pref("hide_values") and formatting.is_hidden()
        assert window.header._hidden
        window.header.privacy_toggled.emit()
        assert not formatting.is_hidden()
    finally:
        formatting.set_hidden(False)
    window.header.settings_requested.emit()
    assert window.current == "settings"


def test_default_range_pref_applies_to_every_page(window):
    window.workspace.set_pref("default_range", "6M")
    for key in ["overview"] + [a.id for a in window.workspace.agents]:
        assert window.dashboard(key).total.range_key == "6M"


@pytest.mark.parametrize("kind", ["crypto", "total", "summary", "activity", "decisions", "agents", "coin"])
def test_every_card_expands_and_collapses(window, kind):
    dash = window.dashboard("overview")  # só o Geral tem todos os 7 cards expansíveis
    window.expand(dash, kind, getattr(dash, kind))
    assert window.overlay.state == "open"
    window.overlay.collapse(animate=False)
    assert window.overlay.state == "closed" and not window.overlay.isVisible()


def test_card_body_click_requests_expand(window):
    from PySide6.QtCore import QPoint, Qt
    from PySide6.QtTest import QTest

    card = window.dashboard("overview").crypto
    hits = []
    card.expand_requested.connect(lambda: hits.append(1))
    QTest.mouseClick(card, Qt.MouseButton.LeftButton, pos=QPoint(4, 4))
    assert hits == [1]


def test_swap_card_is_not_expandable(window):
    dash = window.dashboard(window.workspace.agents[0].id)
    assert dash.exchange._hint is None
    assert dash.crypto._hint is not None


def test_switching_tabs_closes_the_expanded_view(window):
    dash = window.dashboard("overview")
    window.expand(dash, "total", dash.total)
    window.select(window.workspace.agents[0].id)
    assert window.overlay.state == "closed"


def test_agent_row_click_inside_expanded_view_opens_the_tab(window):
    dash = window.dashboard("overview")
    window.expand(dash, "agents", dash.agents)
    target = window.workspace.agents[1]
    dash.open_agent.emit(target.id)
    assert window.current == target.id and window.overlay.state == "closed"


def test_new_agent_tab_grows_in(app):
    w = MainWindow(Workspace(), animations=True)
    w.show()
    app.processEvents()
    agent = w.workspace.add("Nova")
    assert agent.id in w.header._appear and w.header._appear[agent.id] < 1.0
    w.close()


def test_decision_filter_in_expanded_list(window):
    from ubento.ui.cards.decisions import DecisionList

    store = window.workspace.agents[0].store
    lst = DecisionList(store)
    total = len(lst.items())
    lst.set_filter("swap")
    assert len(lst.items()) == 0
    store.execute("USD", "ETH", 500)
    assert len(lst.items()) == 1 and len(store.decisions) == total + 1


def test_config_page_opens_and_keeps_the_agent_tab_highlighted(window):
    agent = window.workspace.agents[0]
    window.open_config(agent.id)
    assert window.current == f"cfg:{agent.id}"
    assert window.header._current == agent.id


def test_config_page_edits_the_agent(window):
    agent = window.workspace.agents[0]
    window.open_config(agent.id)
    page = window.pages[f"cfg:{agent.id}"].widget()

    page.strategy_cards["dca"].click()
    assert agent.config.strategy == "dca"
    assert page.param_rows["trade_size_pct"].isVisibleTo(page)
    assert not page.param_rows["stop_loss_pct"].isVisibleTo(page)

    page.sliders["reserve_pct"].valueChanged.emit(35)
    assert agent.config.reserve_pct == 35

    page.mode_buttons["buttons"]["auto"].click()
    assert agent.config.mode == "auto"

    page.chips["BNB"].click()
    assert "BNB" not in agent.config.assets
    page.swatches.picked.emit("#EF4B3F")
    assert agent.color == "#EF4B3F"


def test_config_page_refuses_to_clear_all_assets(window):
    agent = window.workspace.agents[0]
    window.open_config(agent.id)
    page = window.pages[f"cfg:{agent.id}"].widget()
    window.workspace.set_config(agent.id, assets=["ETH"])
    page.chips["ETH"].setChecked(False)
    page._assets_changed()
    assert agent.config.assets == ["ETH"]


def test_manual_strategy_hides_limits_and_disables_run(window):
    agent = window.workspace.agents[0]
    window.open_config(agent.id)
    page = window.pages[f"cfg:{agent.id}"].widget()
    page.strategy_cards["manual"].click()
    assert not page.sections["limits"].isVisibleTo(page)
    assert not page.run.isEnabled()


def test_agent_bar_runs_and_proposals_can_be_approved(window):
    agent = window.workspace.agents[0]
    window.workspace.set_config(agent.id, strategy="dca", mode="approve")
    dash = window.dashboard(agent.id)
    dash.bar.run_requested.emit()
    assert window.workspace.pending_count(agent.id) == 1
    assert window.header._tabs[1].pending == 1
    uid = next(d.uid for d in agent.store.decisions if d.status == "proposed")
    usd = agent.store.holdings["USD"]
    dash.decisions.resolve_requested.emit(uid, True)
    assert agent.store.holdings["USD"] == usd  # ✓ aprova, mas NÃO executa
    assert window.workspace.pending_count(agent.id) == 1 and window.header._tabs[1].pending == 1
    dash.registrar_execucao(uid)  # passo separado: a execução foi confirmada
    assert agent.store.holdings["USD"] < usd
    assert window.workspace.pending_count(agent.id) == 0 and window.header._tabs[1].pending == 0


def test_decision_list_buttons_hit_testing(window):
    from PySide6.QtCore import QPointF

    agent = window.workspace.agents[0]
    window.workspace.set_config(agent.id, strategy="dca", mode="approve")
    window.workspace.run_agent(agent.id)
    lst = window.dashboard(agent.id).decisions.list
    lst.resize(480, 300)
    ok, no = lst._buttons(0)
    hits = []
    lst.resolve_requested.connect(lambda uid, approve: hits.append(approve))
    assert lst._hit_button(ok.center())[1] is True
    assert lst._hit_button(no.center())[1] is False
    assert lst._hit_button(QPointF(20, 20)) is None


def test_removing_an_agent_drops_its_config_page(window):
    ws = window.workspace
    extra = ws.add("Temp")
    window.open_config(extra.id)
    assert f"cfg:{extra.id}" in window.pages
    ws.remove(extra.id)
    assert f"cfg:{extra.id}" not in window.pages and window.current == "overview"


def test_approved_decision_shows_a_register_button_that_asks_for_execution(window):
    from PySide6.QtCore import QPointF

    from ubento.ui.cards.decisions import ROW_H

    agent = window.workspace.agents[0]
    window.workspace.set_config(agent.id, strategy="dca", mode="approve")
    window.workspace.run_agent(agent.id)
    uid = next(d.uid for d in agent.store.decisions if d.status == "proposed")
    window.workspace.resolve_decision(uid, True)
    lst = window.dashboard(agent.id).decisions.list
    lst.resize(480, 300)
    linha = next(i for i, d in enumerate(lst.items()) if d.uid == uid)
    caixa = lst._registrar_rect(linha * ROW_H - lst._offset)
    decisao, acao = lst._hit_button(caixa.center())
    assert decisao.uid == uid and acao is None  # None = "registrar execução" (nem aprovar, nem recusar)
    assert lst._hit_button(QPointF(10, caixa.center().y())) is None


def test_metas_page_imports_and_steps_and_decisions_do_not_touch_progress(window):
    from pathlib import Path

    agent = window.workspace.agents[0]
    cenario = Path(__file__).resolve().parent.parent / "exemplos" / "avaliacao" / "01_parcial_ate_atingir.yaml"
    window.open_metas(agent.id)
    page = window.pages["metas:" + agent.id].widget()
    assert window.current == "metas:" + agent.id and window.header._current == agent.id  # a aba do agente segue destacada
    assert not page.avancar.isEnabled()  # sem meta ainda
    page.importar_arquivo(str(cenario))
    assert page.avancar.isEnabled() and page.meta_id
    antes = window.metas.painel(page.meta_id)
    assert antes.estado is None
    page.avancar.clicked.emit()
    depois = window.metas.painel(page.meta_id)
    assert depois.estado is not None and depois.progresso.quantidade_comprovada >= 0
    # aprovar/recusar/registrar decisões do agente NÃO mexe no progresso das metas
    window.workspace.set_config(agent.id, strategy="dca", mode="approve")
    window.workspace.run_agent(agent.id)
    uid = next(d.uid for d in agent.store.decisions if d.status == "proposed")
    window.workspace.resolve_decision(uid, True)
    window.workspace.registrar_execucao(uid)
    assert window.metas.painel(page.meta_id).progresso == depois.progresso
    assert window.metas.repo.eventos(page.meta_id) == list(depois.eventos)
