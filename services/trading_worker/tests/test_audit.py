from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest

from device_core.db.models import AccountSnapshot

import trading_worker.audit as audit_module
from trading_worker.audit import (
    audit_algorithm_layer,
    audit_cycle,
    audit_execution_layer,
    list_recent_cycles,
)
from trading_worker.loop import NETTED_ORDER_BOT_SLUG, run_cycle


class FakeAlpacaClient:
    def __init__(self, *, equity=1000.0, cash=100.0, position_values=None):
        self._equity = equity
        self._cash = cash
        self._position_values = dict(position_values or {})
        self.submitted_orders = []

    def get_account(self):
        return SimpleNamespace(equity=self._equity, cash=self._cash)

    def list_position_values(self):
        return dict(self._position_values)

    def submit_order(self, *, symbol, side, qty=None, notional=None):
        self.submitted_orders.append({"symbol": symbol, "side": side, "qty": qty, "notional": notional})
        return SimpleNamespace(alpaca_order_id=f"order-{len(self.submitted_orders)}", status="accepted", raw={"symbol": symbol})


def _signal(bot_id, bot_type, *, signal, target_weights=None, state=None, note="test"):
    return {
        "bot_id": bot_id,
        "bot_type": bot_type,
        "ts": datetime.now(timezone.utc),
        "signal": signal,
        "note": note,
        "payload": {"target_weights": target_weights or {}},
        "state": state,
    }


def _patch_registry(monkeypatch, entries: dict[str, tuple[str, object]]):
    """entries: engine_slug -> (signal_bot_type, runner_fn)."""
    monkeypatch.setattr(
        audit_module, "get_algorithm", lambda slug: SimpleNamespace(bot_type=entries[slug][0]) if slug in entries else None
    )
    monkeypatch.setattr(audit_module, "get_runner", lambda slug: entries[slug][1] if slug in entries else None)


# --- Execution-fidelity layer -----------------------------------------------
#
# audit_execution_layer(core, cycle_ts) takes any timestamp directly - most
# tests below pick one explicitly rather than discovering it via
# list_recent_cycles(), so a test can exercise a scenario (e.g. an order
# that never got submitted) without needing that very order to exist to
# find the cycle in the first place.


def test_execution_layer_matches_a_normal_cycle(core, monkeypatch):
    """A cycle produced by the real run_cycle() must audit as a clean match
    against its own recorded data, discovered the same way a real caller
    would (list_recent_cycles(), from the order it just submitted)."""
    core.strategies.upsert(bot_slug="force", params={})
    import trading_worker.loop as loop_module

    monkeypatch.setattr(loop_module, "get_algorithm", lambda slug: object())
    monkeypatch.setattr(
        loop_module, "get_runner", lambda slug: (lambda config, state: _signal("force", "alpha1", signal="REBALANCE", target_weights={"AAPL": 1.0}))
    )
    alpaca = FakeAlpacaClient(equity=1000.0, position_values={})
    run_cycle(core, alpaca)

    [cycle] = list_recent_cycles(core, limit=1)
    result = audit_execution_layer(core, cycle["ts"])

    assert result.status == "match"
    assert [line.status for line in result.lines] == ["match"]
    assert result.lines[0].symbol == "AAPL"


def test_execution_layer_flags_a_tampered_order(core):
    """A corrupted/incorrect order in the `order` table (simulating a real
    execution bug) must be caught as a notional_mismatch, not silently
    accepted."""
    core.strategies.upsert(bot_slug="force", params={})
    core.allocations.replace(bot_slug="force", target_weights={"AAPL": 1.0}, current_weights={})
    core.account_snapshots.record(equity=1000.0, cash=0.0)
    cycle_ts = datetime.now(timezone.utc)

    # Correct plan would buy $1000 of AAPL - record a wrong (too small) buy.
    core.orders.record(bot_slug=NETTED_ORDER_BOT_SLUG, symbol="AAPL", side="buy", notional=500.0, status="accepted")

    result = audit_execution_layer(core, cycle_ts)

    assert result.status == "mismatch"
    [line] = result.lines
    assert line.status == "notional_mismatch"
    assert line.expected_notional == pytest.approx(1000.0)
    assert line.actual_notional == pytest.approx(500.0)


def test_execution_layer_flags_a_missing_order(core):
    """A target allocation that should have produced a trade, but has no
    corresponding order recorded, must be flagged as missing."""
    core.strategies.upsert(bot_slug="force", params={})
    core.allocations.replace(bot_slug="force", target_weights={"AAPL": 1.0}, current_weights={})
    core.account_snapshots.record(equity=1000.0, cash=0.0)
    cycle_ts = datetime.now(timezone.utc)

    result = audit_execution_layer(core, cycle_ts)

    assert result.status == "mismatch"
    [line] = result.lines
    assert line.status == "missing"
    assert line.symbol == "AAPL"
    assert line.actual_notional is None


def test_execution_layer_excludes_locked_symbols_from_manageable_equity(core):
    core.manual_holdings.add(symbol="TSLA", target_qty=5.0)
    core.positions.record(
        symbol="TSLA", qty=1.0, avg_entry_price=400.0, current_price=400.0, market_value=400.0,
        unrealized_pl=0.0, unrealized_plpc=0.0, unrealized_intraday_plpc=0.0,
    )
    core.strategies.upsert(bot_slug="force", params={})
    core.allocations.replace(bot_slug="force", target_weights={"AAPL": 1.0}, current_weights={})
    core.account_snapshots.record(equity=1000.0, cash=0.0)
    cycle_ts = datetime.now(timezone.utc)

    core.orders.record(bot_slug=NETTED_ORDER_BOT_SLUG, symbol="AAPL", side="buy", notional=600.0, status="accepted")

    result = audit_execution_layer(core, cycle_ts)

    assert result.manageable_equity == pytest.approx(600.0)
    assert result.locked_symbols == ["TSLA"]
    assert result.status == "match"


def test_execution_layer_reports_no_orders_expected_or_found_when_nothing_active(core):
    core.account_snapshots.record(equity=1000.0, cash=1000.0)
    cycle_ts = datetime.now(timezone.utc)

    result = audit_execution_layer(core, cycle_ts)

    assert result.status == "no_orders_expected_or_found"
    assert result.lines == []


# --- Algorithm-fidelity layer ------------------------------------------------
#
# audit_algorithm_layer(core, cycle_ts) doesn't depend on account_snapshot
# or order data at all (only strategy_config + signal), so these tests pick
# cycle_ts directly.


def test_algorithm_layer_matches_when_replay_agrees(core, monkeypatch):
    core.strategies.upsert(bot_slug="force", params={"top_n": 1})
    core.signals.store(bot_id="force", bot_type="alpha1", signal="REBALANCE", payload={"target_weights": {"AAPL": 1.0}})
    cycle_ts = datetime.now(timezone.utc)

    _patch_registry(monkeypatch, {"force": ("alpha1", lambda config, state: _signal("force", "alpha1", signal="REBALANCE", target_weights={"AAPL": 1.0}))})

    [result] = audit_algorithm_layer(core, cycle_ts)

    assert result.status == "match"
    assert result.recorded_signal == "REBALANCE"
    assert result.replayed_signal == "REBALANCE"


def test_algorithm_layer_reports_mismatch_when_replay_disagrees(core, monkeypatch):
    core.strategies.upsert(bot_slug="force", params={})
    core.signals.store(bot_id="force", bot_type="alpha1", signal="REBALANCE", payload={"target_weights": {"AAPL": 1.0}})
    cycle_ts = datetime.now(timezone.utc)

    _patch_registry(monkeypatch, {"force": ("alpha1", lambda config, state: _signal("force", "alpha1", signal="REBALANCE", target_weights={"MSFT": 1.0}))})

    [result] = audit_algorithm_layer(core, cycle_ts)

    assert result.status == "mismatch"
    assert result.recorded_target_weights == {"AAPL": 1.0}
    assert result.replayed_target_weights == {"MSFT": 1.0}


def test_algorithm_layer_skips_when_no_recorded_signal_yet(core, monkeypatch):
    core.strategies.upsert(bot_slug="force", params={})
    cycle_ts = datetime.now(timezone.utc)

    _patch_registry(monkeypatch, {"force": ("alpha1", lambda config, state: _signal("force", "alpha1", signal="HOLD"))})

    [result] = audit_algorithm_layer(core, cycle_ts)

    assert result.status == "skipped"
    assert "No recorded signal" in result.detail


def test_algorithm_layer_replays_a_stateful_bots_first_ever_cycle(core, monkeypatch):
    """draco's very first recorded cycle has a known prior_state (None) -
    replay is valid and must not be skipped."""
    core.strategies.upsert(bot_slug="draco", params={})
    core.signals.store(bot_id="draco", bot_type="draco", signal="HOLD", payload={})
    cycle_ts = datetime.now(timezone.utc)

    received_states = []

    def fake_runner(config, state):
        received_states.append(state)
        return _signal("draco", "draco", signal="HOLD")

    _patch_registry(monkeypatch, {"draco": ("draco", fake_runner)})

    [result] = audit_algorithm_layer(core, cycle_ts)

    assert received_states == [None]
    assert result.status == "match"


def test_algorithm_layer_skips_a_stateful_bots_later_cycle(core, monkeypatch):
    """draco's SECOND cycle onward has no recoverable prior_state
    (device_core.BotState only keeps current state) - must be skipped, not
    silently replayed against the wrong state."""
    core.strategies.upsert(bot_slug="draco", params={})
    now = datetime.now(timezone.utc)
    core.signals.store(bot_id="draco", bot_type="draco", signal="HOLD", payload={}, ts=now - timedelta(minutes=10))
    core.signals.store(bot_id="draco", bot_type="draco", signal="REBALANCE", payload={"target_weights": {"NVDA": 1.0}}, ts=now)

    _patch_registry(monkeypatch, {"draco": ("draco", lambda config, state: _signal("draco", "draco", signal="HOLD"))})

    [result] = audit_algorithm_layer(core, now)

    assert result.status == "skipped"
    assert "Stateful bot" in result.detail
    assert result.recorded_signal == "REBALANCE"


def test_algorithm_layer_flags_stale_replay_for_a_cycle_not_from_today(core, monkeypatch):
    core.strategies.upsert(bot_slug="force", params={})
    core.signals.store(bot_id="force", bot_type="alpha1", signal="HOLD", payload={})
    cycle_ts = datetime.now(timezone.utc)

    _patch_registry(monkeypatch, {"force": ("alpha1", lambda config, state: _signal("force", "alpha1", signal="HOLD"))})

    fake_today = cycle_ts + timedelta(days=1)
    [result] = audit_algorithm_layer(core, cycle_ts, today=fake_today)

    assert result.stale_replay is True


# --- Top-level orchestration --------------------------------------------------
#
# list_recent_cycles/audit_cycle identify cycles from `order` timestamps
# (see audit.py's module docstring for why account_snapshot rows can't be
# used - main.py's separate ~60s heartbeat writes those too).


def _record_order_cycle(core, *, equity, symbol="AAPL", notional=1000.0, submitted_at=None):
    """Records an account_snapshot AND an order backdated to the same
    timestamp - real run_cycle() writes both within the same call, so a
    test simulating a past cycle needs both consistently backdated (a
    snapshot inserted "for real" just now, with only the order backdated,
    would land AFTER the order and never be found by
    _account_snapshot_as_of)."""
    snapshot_id = core.account_snapshots.record(equity=equity, cash=0.0)
    if submitted_at is not None:
        with core.database.session() as session:
            row = session.query(AccountSnapshot).filter_by(id=snapshot_id).one()
            row.ts = submitted_at
    core.orders.record(
        bot_slug=NETTED_ORDER_BOT_SLUG, symbol=symbol, side="buy", notional=notional, status="accepted",
        submitted_at=submitted_at,
    )


def test_list_recent_cycles_clusters_orders_most_recent_first(core):
    now = datetime.now(timezone.utc)
    _record_order_cycle(core, equity=100.0, submitted_at=now - timedelta(minutes=10))
    _record_order_cycle(core, equity=200.0, submitted_at=now)

    cycles = list_recent_cycles(core)

    assert [c["equity"] for c in cycles] == [200.0, 100.0]


def test_list_recent_cycles_groups_same_cycles_orders_into_one_entry(core):
    """Two orders from the SAME cycle (well within CORRELATION_WINDOW_SECONDS
    of each other, e.g. a sell then a buy in one run_cycle() call) must
    collapse into a single listed cycle, not two."""
    now = datetime.now(timezone.utc)
    core.account_snapshots.record(equity=1000.0, cash=0.0)
    core.orders.record(bot_slug=NETTED_ORDER_BOT_SLUG, symbol="AAPL", side="sell", notional=100.0, status="accepted", submitted_at=now)
    core.orders.record(bot_slug=NETTED_ORDER_BOT_SLUG, symbol="MSFT", side="buy", notional=100.0, status="accepted", submitted_at=now + timedelta(seconds=1))

    cycles = list_recent_cycles(core)

    assert len(cycles) == 1


def test_audit_cycle_selects_by_index(core):
    now = datetime.now(timezone.utc)
    _record_order_cycle(core, equity=100.0, submitted_at=now - timedelta(minutes=10))
    _record_order_cycle(core, equity=200.0, submitted_at=now)

    latest = audit_cycle(core, cycle_index=0)
    older = audit_cycle(core, cycle_index=1)

    assert latest.execution_result.manageable_equity == pytest.approx(200.0)
    assert older.execution_result.manageable_equity == pytest.approx(100.0)


def test_audit_cycle_raises_for_out_of_range_index(core):
    with pytest.raises(ValueError):
        audit_cycle(core, cycle_index=0)


def test_audit_cycle_report_includes_caveats(core):
    _record_order_cycle(core, equity=100.0)

    report = audit_cycle(core)

    assert any("historical-as-of" in caveat for caveat in report.caveats)
