import os
from datetime import datetime

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest  # noqa: E402
from PySide6.QtCore import QSettings  # noqa: E402

from ubento.agent_config import PARAMS, RELEVANT, STRATEGIES, AgentConfig, describe, next_run  # noqa: E402
from ubento.engine import decide, momentum  # noqa: E402
from ubento.store import Store  # noqa: E402
from ubento.workspace import Workspace  # noqa: E402

NOW = datetime(2026, 10, 18, 15, 0)


@pytest.fixture
def store():
    return Store(now=NOW)


# -- configuração ---------------------------------------------------------------


def test_config_roundtrip_and_validation():
    cfg = AgentConfig(strategy="dca", risk=9, mode="nope", assets=["ETH", "XYZ"], reserve_pct=-5)
    cfg.validated()
    assert cfg.risk == PARAMS["risk"][1]
    assert cfg.mode == "approve"
    assert cfg.assets == ["ETH"]
    assert cfg.reserve_pct == PARAMS["reserve_pct"][0]
    assert AgentConfig.from_dict(cfg.to_dict()) == cfg


def test_from_dict_ignores_garbage():
    cfg = AgentConfig.from_dict({"strategy": "???", "risk": "abc", "extra": 1})
    assert cfg.strategy == "momentum" and cfg.risk == 3


def test_every_strategy_has_params_and_description():
    for key in STRATEGIES:
        assert key in RELEVANT
        assert describe(AgentConfig(strategy=key))


def test_next_run_is_in_the_future():
    for freq in ("hourly", "daily", "weekly"):
        assert next_run(AgentConfig(frequency=freq), NOW) > NOW


# -- motor ------------------------------------------------------------------------


def test_momentum_signal_is_deterministic_and_bounded():
    assert momentum("ETH", NOW.date()) == momentum("ETH", NOW.date())
    assert all(-15 <= momentum(s, NOW.date()) <= 20 for s in ("ETH", "SOL", "AVAX", "BNB"))


def test_manual_and_paused_agents_decide_nothing(store):
    assert decide(AgentConfig(strategy="manual"), store, NOW) == []
    assert decide(AgentConfig(active=False), store, NOW) == []


@pytest.mark.parametrize("strategy", ["momentum", "rebalance", "dca", "conservative"])
def test_each_strategy_returns_feasible_decisions(store, strategy):
    decisions = decide(AgentConfig(strategy=strategy), store, NOW)
    assert decisions
    probe = Store(now=NOW)
    for d in decisions:
        assert d.title and d.detail
        if d.trade:
            assert d.trade.qty > 0 and probe.apply_trade(d.trade)


def test_higher_risk_buys_more_in_momentum(store):
    def spent(risk):
        cfg = AgentConfig(strategy="momentum", risk=risk, max_position_pct=100)
        return sum(d.trade.usd for d in decide(cfg, store, NOW) if d.trade and d.trade.side == "buy")

    assert spent(5) >= spent(1)


def test_reserve_blocks_buying(store):
    cfg = AgentConfig(strategy="dca", reserve_pct=60)
    store.holdings["USD"] = 100.0  # bem abaixo da reserva
    decisions = decide(cfg, store, NOW)
    assert [d.kind for d in decisions] == ["hold"]


def test_conservative_sells_when_crypto_share_exceeds_limit(store):
    store.holdings["USD"] = 0.0
    store.holdings["USDC"] = 0.0
    decisions = decide(AgentConfig(strategy="conservative", risk=1), store, NOW)
    assert decisions[0].kind == "sell"


# -- store: executar / propor / aprovar -----------------------------------------------


def test_apply_trade_checks_balance(store):
    from ubento.store import Trade

    assert not store.apply_trade(Trade("buy", "ETH", 1.0, 1e9))
    before = store.holdings["ETH"]
    assert store.apply_trade(Trade("buy", "ETH", 0.1, 385.0))
    assert store.holdings["ETH"] == pytest.approx(before + 0.1)


def test_proposal_does_not_move_money_until_approved(store):
    from dataclasses import replace

    d = replace(decide(AgentConfig(strategy="dca"), store, NOW)[0], status="proposed")
    usd = store.holdings["USD"]
    store.add_decision(d)
    assert store.holdings["USD"] == usd
    assert store.resolve_decision(d.uid, True) is None
    assert store.holdings["USD"] < usd
    assert store.decisions[0].status == "executed"


def test_rejected_proposal_changes_nothing(store):
    from dataclasses import replace

    d = replace(decide(AgentConfig(strategy="dca"), store, NOW)[0], status="proposed")
    store.add_decision(d)
    usd = store.holdings["USD"]
    store.resolve_decision(d.uid, False)
    assert store.holdings["USD"] == usd and store.decisions[0].status == "rejected"


# -- workspace -------------------------------------------------------------------------


def test_run_agent_modes():
    ws = Workspace()
    agent = ws.agents[0]
    usd = agent.store.holdings["USD"]

    ws.set_config(agent.id, strategy="dca", mode="approve")
    made, msg = ws.run_agent(agent.id, NOW)
    assert made == 1 and "proposta" in msg and agent.store.holdings["USD"] == usd
    assert ws.pending_count(agent.id) == 1

    ws.set_config(agent.id, mode="auto")
    made, msg = ws.run_agent(agent.id, NOW)
    assert made == 1 and "executada" in msg and agent.store.holdings["USD"] < usd

    ws.set_config(agent.id, mode="suggest")
    usd2 = agent.store.holdings["USD"]
    ws.run_agent(agent.id, NOW)
    assert agent.store.holdings["USD"] == usd2 and agent.store.decisions[0].status == "suggested"


def test_run_agent_refuses_when_paused_or_manual():
    ws = Workspace()
    agent = ws.agents[0]
    ws.set_config(agent.id, active=False)
    assert ws.run_agent(agent.id)[0] == 0
    ws.set_config(agent.id, active=True, strategy="manual")
    assert ws.run_agent(agent.id)[0] == 0


def test_resolve_from_overview_reaches_owner_store():
    ws = Workspace()
    agent = ws.agents[0]
    ws.set_config(agent.id, strategy="dca", mode="approve")
    ws.run_agent(agent.id, NOW)
    uid = next(d.uid for d in ws.overview.decisions if d.status == "proposed")
    assert ws.resolve_decision(uid, True) is None
    assert ws.pending_count() == 0


def test_config_persists_and_duplicates(tmp_path):
    path = str(tmp_path / "cfg.ini")
    ws = Workspace(QSettings(path, QSettings.Format.IniFormat))
    a = ws.agents[0]
    ws.set_config(a.id, strategy="rebalance", risk=5, assets=["ETH", "SOL"], mode="auto")
    copy = ws.duplicate(a.id)
    assert copy.config == a.config and copy.config is not a.config

    again = Workspace(QSettings(path, QSettings.Format.IniFormat))
    cfg = again.agents[0].config
    assert (cfg.strategy, cfg.risk, cfg.assets, cfg.mode) == ("rebalance", 5, ["ETH", "SOL"], "auto")
