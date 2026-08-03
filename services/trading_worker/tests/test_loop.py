from datetime import datetime, timezone

import pytest

import trading_worker.loop as loop_module
from trading_worker.alpaca_client import AccountSnapshot, OrderResult
from trading_worker.loop import run_cycle


class FakeAlpacaClient:
    def __init__(self, *, equity=1000.0, cash=100.0, position_values=None):
        self._equity = equity
        self._cash = cash
        self._position_values = dict(position_values or {})
        self.submitted_orders = []

    def get_account(self):
        return AccountSnapshot(equity=self._equity, cash=self._cash)

    def list_position_values(self):
        return dict(self._position_values)

    def submit_order(self, *, symbol, side, qty=None, notional=None):
        self.submitted_orders.append({"symbol": symbol, "side": side, "qty": qty, "notional": notional})
        return OrderResult(alpaca_order_id=f"order-{len(self.submitted_orders)}", status="accepted", raw={"symbol": symbol})


def _signal(bot_slug, *, signal, target_weights=None, state=None, note="test"):
    return {
        "bot_id": bot_slug,
        "bot_type": "alpha1",
        "ts": datetime.now(timezone.utc),
        "signal": signal,
        "note": note,
        "payload": {"target_weights": target_weights or {}},
        "state": state,
    }


def _patch_registry(monkeypatch, runners: dict):
    monkeypatch.setattr(loop_module, "get_algorithm", lambda slug: object() if slug in runners else None)
    monkeypatch.setattr(loop_module, "get_runner", lambda slug: runners.get(slug))


def test_rebalance_signal_submits_orders_and_persists(core, monkeypatch):
    core.strategies.upsert(bot_slug="force", params={"top_n": 1})
    _patch_registry(monkeypatch, {"force": lambda config, state: _signal("force", signal="REBALANCE", target_weights={"AAPL": 1.0})})
    alpaca = FakeAlpacaClient(equity=1000.0, position_values={})

    results = run_cycle(core, alpaca)

    assert results == [{"bot_slug": "force", "signal": "REBALANCE", "orders": [{"symbol": "AAPL", "side": "buy", "notional": 1000.0}]}]
    assert alpaca.submitted_orders == [{"symbol": "AAPL", "side": "buy", "qty": None, "notional": 1000.0}]

    orders = core.orders.recent(bot_slug="force")
    assert len(orders) == 1
    assert orders[0]["symbol"] == "AAPL"
    assert orders[0]["status"] == "accepted"

    allocation = core.allocations.latest("force")
    assert allocation["target_weights_json"] == {"AAPL": 1.0}

    signal_row = core.signals.latest("force", "alpha1")
    assert signal_row["signal"] == "REBALANCE"

    event_types = [e["type"] for e in core.events.list_unconsumed()]
    assert "signal_generated" in event_types
    assert "trade_executed" in event_types


def test_hold_signal_submits_no_orders(core, monkeypatch):
    core.strategies.upsert(bot_slug="force", params={})
    _patch_registry(monkeypatch, {"force": lambda config, state: _signal("force", signal="HOLD")})
    alpaca = FakeAlpacaClient()

    results = run_cycle(core, alpaca)

    assert results == [{"bot_slug": "force", "signal": "HOLD", "orders": []}]
    assert alpaca.submitted_orders == []
    assert core.orders.recent(bot_slug="force") == []
    assert core.allocations.latest("force") is None
    event_types = [e["type"] for e in core.events.list_unconsumed()]
    assert "trade_executed" not in event_types


def test_bot_state_is_read_before_and_saved_after_run(core, monkeypatch):
    core.strategies.upsert(bot_slug="draco", params={})
    core.bot_states.save("draco", {"positions": {"NVDA": {}}})

    received_states = []

    def fake_runner(config, state):
        received_states.append(state)
        return _signal("draco", signal="HOLD", state={"positions": {}, "round": 2})

    _patch_registry(monkeypatch, {"draco": fake_runner})
    alpaca = FakeAlpacaClient()

    run_cycle(core, alpaca)

    assert received_states == [{"positions": {"NVDA": {}}}]
    assert core.bot_states.get("draco") == {"positions": {}, "round": 2}


def test_one_bot_failure_does_not_abort_the_cycle(core, monkeypatch):
    core.strategies.upsert(bot_slug="force", params={})
    core.strategies.upsert(bot_slug="aptet", params={})

    def failing_runner(config, state):
        raise RuntimeError("boom")

    _patch_registry(
        monkeypatch,
        {
            "force": failing_runner,
            "aptet": lambda config, state: _signal("aptet", signal="HOLD"),
        },
    )
    alpaca = FakeAlpacaClient()

    results = run_cycle(core, alpaca)

    by_slug = {r["bot_slug"]: r for r in results}
    assert by_slug["force"]["error"] == "boom"
    assert by_slug["aptet"]["signal"] == "HOLD"

    error_logs = [row for row in core.logs.recent() if row["component"] == "trading_worker"]
    assert len(error_logs) == 1
    assert "force" in error_logs[0]["message"]


def test_run_cycle_records_account_snapshot_even_with_no_active_bots(core):
    alpaca = FakeAlpacaClient(equity=500.0, cash=50.0)

    results = run_cycle(core, alpaca)

    assert results == []
    snapshots = core.account_snapshots.recent()
    assert len(snapshots) == 1
    assert snapshots[0]["equity"] == 500.0


def test_locked_holding_absent_from_target_weights_is_never_sold(core, monkeypatch):
    """The concrete bug this whole exclusion mechanism exists to prevent:
    a locked TSLA position with no corresponding bot target weight must
    NOT be treated as "should be fully exited"."""
    core.manual_holdings.add(symbol="TSLA", target_qty=5.0)
    core.strategies.upsert(bot_slug="force", params={})
    _patch_registry(monkeypatch, {"force": lambda config, state: _signal("force", signal="REBALANCE", target_weights={"AAPL": 1.0})})
    alpaca = FakeAlpacaClient(equity=1000.0, position_values={"TSLA": 300.0})

    run_cycle(core, alpaca)

    assert not any(o["symbol"] == "TSLA" for o in alpaca.submitted_orders)


def test_locked_holding_in_bot_target_weights_is_dropped_and_renormalized(core, monkeypatch):
    core.manual_holdings.add(symbol="TSLA", target_qty=5.0)
    core.strategies.upsert(bot_slug="force", params={})
    _patch_registry(
        monkeypatch,
        {"force": lambda config, state: _signal("force", signal="REBALANCE", target_weights={"AAPL": 0.5, "TSLA": 0.5})},
    )
    alpaca = FakeAlpacaClient(equity=1000.0, position_values={})

    run_cycle(core, alpaca)

    assert not any(o["symbol"] == "TSLA" for o in alpaca.submitted_orders)
    allocation = core.allocations.latest("force")
    assert allocation["target_weights_json"] == {"AAPL": 1.0}  # renormalized after TSLA dropped


def test_all_target_symbols_locked_skips_rebalance_entirely(core, monkeypatch):
    core.manual_holdings.add(symbol="AAPL", target_qty=5.0)
    core.strategies.upsert(bot_slug="force", params={})
    _patch_registry(monkeypatch, {"force": lambda config, state: _signal("force", signal="REBALANCE", target_weights={"AAPL": 1.0})})
    alpaca = FakeAlpacaClient(equity=1000.0, position_values={})

    results = run_cycle(core, alpaca)

    assert results == [{"bot_slug": "force", "signal": "REBALANCE", "orders": []}]
    assert alpaca.submitted_orders == []
    assert core.allocations.latest("force") is None


def test_runner_lookup_uses_bot_type_not_bot_slug_when_present(core, monkeypatch):
    """Real monstra.pro-synced rows store bot_slug as a per-instance monster
    identity (e.g. "vectura_draco") separate from bot_type (the engine
    family, "draco") - the registry lookup must use bot_type, not bot_slug,
    once bot_type is set."""
    core.strategies.upsert(bot_slug="vectura_draco", bot_type="draco", params={}, source="monstra.pro")
    _patch_registry(monkeypatch, {"draco": lambda config, state: _signal("vectura_draco", signal="HOLD")})
    alpaca = FakeAlpacaClient()

    results = run_cycle(core, alpaca)

    assert results == [{"bot_slug": "vectura_draco", "signal": "HOLD", "orders": []}]


def test_runner_lookup_falls_back_to_bot_slug_when_bot_type_is_none(core, monkeypatch):
    """Locally/test-seeded rows predating bot_selection_sync never set
    bot_type - bot_slug itself must still resolve as the engine slug."""
    core.strategies.upsert(bot_slug="force", params={})  # no bot_type
    _patch_registry(monkeypatch, {"force": lambda config, state: _signal("force", signal="HOLD")})
    alpaca = FakeAlpacaClient()

    results = run_cycle(core, alpaca)

    assert results == [{"bot_slug": "force", "signal": "HOLD", "orders": []}]


def test_locked_value_is_excluded_from_manageable_equity(core, monkeypatch):
    """400 of the account's 1000 equity is a locked TSLA position - the bot
    should size its AAPL buy against the remaining 600, not the full 1000."""
    core.manual_holdings.add(symbol="TSLA", target_qty=5.0)
    core.strategies.upsert(bot_slug="force", params={})
    _patch_registry(monkeypatch, {"force": lambda config, state: _signal("force", signal="REBALANCE", target_weights={"AAPL": 1.0})})
    alpaca = FakeAlpacaClient(equity=1000.0, position_values={"TSLA": 400.0})

    run_cycle(core, alpaca)

    [order] = alpaca.submitted_orders
    assert order["symbol"] == "AAPL"
    assert order["notional"] == pytest.approx(600.0)
