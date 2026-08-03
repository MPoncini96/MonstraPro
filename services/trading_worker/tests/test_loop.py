from datetime import datetime, timezone

import pytest

import trading_worker.loop as loop_module
from trading_worker.alpaca_client import AccountSnapshot, OrderResult
from trading_worker.loop import NETTED_ORDER_BOT_SLUG, run_cycle


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

    assert results == [{"bot_slug": "force", "signal": "REBALANCE", "desired_weights": {"AAPL": 1.0}}]
    assert alpaca.submitted_orders == [{"symbol": "AAPL", "side": "buy", "qty": None, "notional": 1000.0}]

    # Recorded under the synthetic netted-order slug, not the originating
    # bot's own slug - see loop.py's module docstring on why per-bot order
    # attribution is dropped once orders can combine multiple bots' trades.
    orders = core.orders.recent(bot_slug=NETTED_ORDER_BOT_SLUG)
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

    assert results == [{"bot_slug": "force", "signal": "HOLD", "desired_weights": None}]
    assert alpaca.submitted_orders == []
    assert core.orders.recent(bot_slug=NETTED_ORDER_BOT_SLUG) == []
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

    assert results == [{"bot_slug": "force", "signal": "REBALANCE", "desired_weights": None}]
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

    assert results == [{"bot_slug": "vectura_draco", "signal": "HOLD", "desired_weights": None}]


def test_runner_lookup_falls_back_to_bot_slug_when_bot_type_is_none(core, monkeypatch):
    """Locally/test-seeded rows predating bot_selection_sync never set
    bot_type - bot_slug itself must still resolve as the engine slug."""
    core.strategies.upsert(bot_slug="force", params={})  # no bot_type
    _patch_registry(monkeypatch, {"force": lambda config, state: _signal("force", signal="HOLD")})
    alpaca = FakeAlpacaClient()

    results = run_cycle(core, alpaca)

    assert results == [{"bot_slug": "force", "signal": "HOLD", "desired_weights": None}]


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


# --- Cross-bot equity weighting + netting ----------------------------------


def test_all_bots_default_to_equal_weight_when_unset(core, monkeypatch):
    """Today's exact live scenario: several bots selected on monstra.pro
    with no equity_weight configured at all must split the account evenly,
    not each assume 100%."""
    core.strategies.upsert(bot_slug="force", params={})
    core.strategies.upsert(bot_slug="aptet", params={})
    _patch_registry(
        monkeypatch,
        {
            "force": lambda config, state: _signal("force", signal="REBALANCE", target_weights={"AAPL": 1.0}),
            "aptet": lambda config, state: _signal("aptet", signal="REBALANCE", target_weights={"MSFT": 1.0}),
        },
    )
    alpaca = FakeAlpacaClient(equity=1000.0, position_values={})

    run_cycle(core, alpaca)

    orders_by_symbol = {o["symbol"]: o for o in alpaca.submitted_orders}
    assert orders_by_symbol["AAPL"]["notional"] == pytest.approx(500.0)
    assert orders_by_symbol["MSFT"]["notional"] == pytest.approx(500.0)


def test_bots_with_different_equity_weights_split_proportionally(core, monkeypatch):
    core.strategies.upsert(bot_slug="force", equity_weight=3.0, params={})
    core.strategies.upsert(bot_slug="aptet", equity_weight=1.0, params={})
    _patch_registry(
        monkeypatch,
        {
            "force": lambda config, state: _signal("force", signal="REBALANCE", target_weights={"AAPL": 1.0}),
            "aptet": lambda config, state: _signal("aptet", signal="REBALANCE", target_weights={"MSFT": 1.0}),
        },
    )
    alpaca = FakeAlpacaClient(equity=1000.0, position_values={})

    run_cycle(core, alpaca)

    orders_by_symbol = {o["symbol"]: o for o in alpaca.submitted_orders}
    assert orders_by_symbol["AAPL"]["notional"] == pytest.approx(750.0)
    assert orders_by_symbol["MSFT"]["notional"] == pytest.approx(250.0)


def test_overlapping_bots_produce_one_net_order_instead_of_colliding(core, monkeypatch):
    """The actual regression test for the live bug: two bots both want to
    exit the same already-held symbol in the same cycle. Under the old
    per-bot-submits-independently code, each bot would have computed its
    OWN full-exit sell order against the SAME shared position, and only the
    first submission would succeed - the second would hit Alpaca's real
    qty check and fail with "insufficient qty available" (exactly what
    happened live with 5 bots and a shared ERX position). Netting must
    produce exactly ONE sell order for the correct combined amount."""
    core.strategies.upsert(bot_slug="force", params={})
    core.strategies.upsert(bot_slug="aptet", params={})
    _patch_registry(
        monkeypatch,
        {
            "force": lambda config, state: _signal("force", signal="REBALANCE", target_weights={"AAPL": 1.0}),
            "aptet": lambda config, state: _signal("aptet", signal="REBALANCE", target_weights={"MSFT": 1.0}),
        },
    )
    # Neither bot's target includes ERX - both independently want out of it.
    alpaca = FakeAlpacaClient(equity=1000.0, position_values={"ERX": 300.0})

    run_cycle(core, alpaca)

    erx_orders = [o for o in alpaca.submitted_orders if o["symbol"] == "ERX"]
    assert len(erx_orders) == 1
    assert erx_orders[0]["side"] == "sell"
    assert erx_orders[0]["notional"] == pytest.approx(300.0)


def test_hold_bots_carried_forward_allocation_is_reexcluded_against_a_newly_locked_symbol(core, monkeypatch):
    """A symbol can be locked (services/portfolio_web) after a bot's last
    real REBALANCE - its carried-forward allocation (from
    core.allocations.latest) must be re-run through exclude_locked_symbols
    against THIS cycle's locks, not just whatever was true when it was
    originally written, or a stale allocation could reintroduce a
    now-locked symbol into the combined pool."""
    core.strategies.upsert(bot_slug="force", params={})
    core.allocations.replace(bot_slug="force", target_weights={"AAPL": 0.5, "TSLA": 0.5}, current_weights={})
    core.manual_holdings.add(symbol="TSLA", target_qty=5.0)  # locked AFTER that allocation was written
    _patch_registry(monkeypatch, {"force": lambda config, state: _signal("force", signal="HOLD")})
    alpaca = FakeAlpacaClient(equity=1000.0, position_values={})

    run_cycle(core, alpaca)

    assert not any(o["symbol"] == "TSLA" for o in alpaca.submitted_orders)
    [order] = alpaca.submitted_orders
    assert order["symbol"] == "AAPL"
    assert order["notional"] == pytest.approx(1000.0)  # TSLA dropped, AAPL renormalized to 100%


def test_locked_symbol_excluded_from_combined_pool_even_if_only_one_bot_targets_it(core, monkeypatch):
    core.manual_holdings.add(symbol="TSLA", target_qty=5.0)
    core.strategies.upsert(bot_slug="force", params={})
    core.strategies.upsert(bot_slug="aptet", params={})
    _patch_registry(
        monkeypatch,
        {
            "force": lambda config, state: _signal("force", signal="REBALANCE", target_weights={"AAPL": 0.5, "TSLA": 0.5}),
            "aptet": lambda config, state: _signal("aptet", signal="REBALANCE", target_weights={"MSFT": 1.0}),
        },
    )
    alpaca = FakeAlpacaClient(equity=1000.0, position_values={})

    run_cycle(core, alpaca)

    assert not any(o["symbol"] == "TSLA" for o in alpaca.submitted_orders)


def test_failed_bot_falls_back_to_last_known_allocation_instead_of_forcing_a_sale(core, monkeypatch):
    """A transient strategy-engine error must not force-sell whatever the
    bot was previously holding - it should carry forward its last known
    allocation, same as a HOLD signal would."""
    core.strategies.upsert(bot_slug="force", params={})
    core.allocations.replace(bot_slug="force", target_weights={"AAPL": 1.0}, current_weights={})

    def failing_runner(config, state):
        raise RuntimeError("boom")

    _patch_registry(monkeypatch, {"force": failing_runner})
    alpaca = FakeAlpacaClient(equity=1000.0, position_values={"AAPL": 1000.0})

    run_cycle(core, alpaca)

    assert alpaca.submitted_orders == []  # already at its last known target - nothing to trade
