import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from ubento.store import Store  # noqa: E402
from ubento.ui import theme  # noqa: E402
from ubento.ui.main_window import MainWindow  # noqa: E402


@pytest.fixture(scope="module")
def app():
    a = QApplication.instance() or QApplication([])
    a.setStyleSheet(theme.APP_QSS)
    return a


@pytest.fixture
def window(app):
    w = MainWindow(Store())
    w.show()
    app.processEvents()
    yield w
    w.close()


def test_exchange_button_runs_the_swap(window):
    ex, store = window.exchange, window.store
    usd = store.holdings["USD"]
    ex.send_panel.input.setText("500")
    assert ex.button._reason is None
    ex._submit()
    assert store.holdings["USD"] == pytest.approx(usd - 500)
    assert store.transfers[0].title == "USD para ETH"


def test_exchange_blocks_invalid_amount(window):
    ex = window.exchange
    ex.send_panel.input.setText("99999999")
    assert ex.button._reason == "Saldo insuficiente"
    ex.send_panel.input.setText("")
    assert ex.button._reason == "Informe um valor"


def test_swap_button_inverts_sides(window):
    ex = window.exchange
    ex.swap_sides()
    assert (ex.send, ex.receive) == ("ETH", "USD")


def test_picking_the_other_side_currency_inverts(window):
    ex = window.exchange
    ex._pick("send", "ETH")
    assert (ex.send, ex.receive) == ("ETH", "USD")


def test_range_change_updates_chart_and_total(window):
    card = window.total
    card.set_range("1A")
    assert len(card.chart._points) == 52
    card.set_range("1S")
    assert len(card.chart._points) == 7


def test_buy_usdc_shortcut_prefills_exchange(window):
    window.coin.buy_clicked.emit()
    assert (window.exchange.send, window.exchange.receive) == ("USD", "USDC")
