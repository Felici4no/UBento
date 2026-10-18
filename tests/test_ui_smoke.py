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
    w = MainWindow(Workspace())
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
    assert store.transfers[0].title == "USD para ETH"


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
    dash = window.dashboard("overview")
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
    assert agent_menu == ["Renomear…", "Cor", "Duplicar", "Mover para a esquerda", "Mover para a direita", "Remover"]
