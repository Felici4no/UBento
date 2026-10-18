import os
from datetime import datetime

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from ubento.store import GAS_FEE_USD, RANGES, SERVICE_FEE_RATE, Store, make_quote  # noqa: E402


@pytest.fixture
def store(qapp_args=None):
    return Store(now=datetime(2026, 10, 18, 15, 0))


def test_quote_applies_fees_and_rate():
    q = make_quote("USD", "ETH", 1000)
    assert q.service_fee_usd == pytest.approx(1000 * SERVICE_FEE_RATE)
    assert q.gas_fee_usd == GAS_FEE_USD
    assert q.receive_amount == pytest.approx((1000 - 23 - GAS_FEE_USD) / 3852.93)
    assert q.rate == pytest.approx(3852.93)


def test_quote_is_empty_for_invalid_input():
    assert make_quote("USD", "ETH", 0).receive_amount == 0
    assert make_quote("USD", "USD", 100).receive_amount == 0


def test_validate_reasons(store):
    assert store.validate("USD", "USD", 10) == "Escolha moedas diferentes"
    assert store.validate("USD", "ETH", 0) == "Informe um valor"
    assert store.validate("USD", "ETH", 1e9) == "Saldo insuficiente"
    assert store.validate("USD", "ETH", 1) == "Valor menor que as taxas"
    assert store.validate("USD", "ETH", 488.34) is None


def test_execute_moves_balances_and_records_transfer(store):
    before = store.holdings.copy()
    count = len(store.transfers)
    fired = []
    store.changed.connect(lambda: fired.append(1))

    assert store.execute("USD", "ETH", 500) is None

    q = make_quote("USD", "ETH", 500)
    assert store.holdings["USD"] == pytest.approx(before["USD"] - 500)
    assert store.holdings["ETH"] == pytest.approx(before["ETH"] + q.receive_amount)
    assert len(store.transfers) == count + 1
    assert store.transfers[0].title == "USD para ETH"
    assert fired == [1]


def test_execute_rejects_without_side_effects(store):
    before = store.holdings.copy()
    assert store.execute("USD", "ETH", 1e9) == "Saldo insuficiente"
    assert store.holdings == before


@pytest.mark.parametrize("key", list(RANGES))
def test_history_ends_at_current_total(store, key):
    series = store.history(key)
    assert len(series) == RANGES[key][0]
    assert series[-1][1] == pytest.approx(store.total_usd())
    assert all(v > 0 for _, v in series)
    assert [d for d, _ in series] == sorted(d for d, _ in series)


def test_activity_sums_to_transfer_count(store):
    weeks = store.month_weeks()
    assert sum(c or 0 for w in weeks for _, c in w) == store.transfers_count()
