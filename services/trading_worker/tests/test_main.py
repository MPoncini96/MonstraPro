from datetime import date, datetime

import trading_worker.main as main_module
from trading_worker.activation import ActivationStatus
from trading_worker.main import (
    MARKET_TIMEZONE,
    _latest_due_cycle_time,
    _record_snapshots,
    _wait_for_activation,
    scheduled_cycle_times_et,
)


class FakeAlpacaAccount:
    def __init__(self, equity: float, cash: float):
        self.equity = equity
        self.cash = cash


class FakePosition:
    def __init__(self, symbol, *, qty=10.0, avg_entry_price=100.0, current_price=110.0,
                 market_value=1100.0, unrealized_pl=100.0, unrealized_plpc=0.1,
                 unrealized_intraday_plpc=0.02):
        self.symbol = symbol
        self.qty = qty
        self.avg_entry_price = avg_entry_price
        self.current_price = current_price
        self.market_value = market_value
        self.unrealized_pl = unrealized_pl
        self.unrealized_plpc = unrealized_plpc
        self.unrealized_intraday_plpc = unrealized_intraday_plpc


class FakeAlpacaClient:
    def __init__(self, equity: float, cash: float, positions=None):
        self._account = FakeAlpacaAccount(equity, cash)
        self._positions = positions or []

    def get_account(self):
        return self._account

    def list_positions(self):
        return self._positions


def test_records_account_snapshot(core):
    alpaca = FakeAlpacaClient(equity=10250.75, cash=500.0)

    _record_snapshots(core, alpaca)

    [row] = core.account_snapshots.recent()
    assert row["equity"] == 10250.75
    assert row["cash"] == 500.0


def test_repeated_calls_append_rather_than_replace(core):
    _record_snapshots(core, FakeAlpacaClient(equity=10000.0, cash=500.0))
    _record_snapshots(core, FakeAlpacaClient(equity=10100.0, cash=400.0))

    rows = core.account_snapshots.recent()
    assert len(rows) == 2
    assert rows[0]["equity"] == 10100.0  # most-recent-first


def test_records_one_position_snapshot_per_held_position(core):
    alpaca = FakeAlpacaClient(
        equity=10000.0, cash=500.0,
        positions=[FakePosition("AAPL"), FakePosition("MSFT", current_price=300.0)],
    )

    _record_snapshots(core, alpaca)

    latest = core.positions.latest_by_symbol()
    assert set(latest.keys()) == {"AAPL", "MSFT"}
    assert latest["MSFT"]["current_price"] == 300.0


def test_no_positions_records_no_position_snapshots(core):
    _record_snapshots(core, FakeAlpacaClient(equity=10000.0, cash=500.0))

    assert core.positions.latest_by_symbol() == {}


def test_records_bot_value_as_target_weighted_price_of_held_symbols(core):
    core.strategies.upsert(bot_slug="force", display_name="Force")
    core.allocations.replace(
        bot_slug="force", target_weights={"AAPL": 0.6, "MSFT": 0.4}, current_weights={"AAPL": 1.0}
    )
    alpaca = FakeAlpacaClient(
        equity=10000.0, cash=500.0,
        positions=[FakePosition("AAPL", current_price=200.0), FakePosition("MSFT", current_price=300.0)],
    )

    _record_snapshots(core, alpaca)

    [row] = core.bot_values.history("force")
    assert row["value"] == 0.6 * 200.0 + 0.4 * 300.0  # target-weighted current price, not account equity


def test_bot_value_only_counts_target_symbols_currently_held(core):
    """A target symbol the bot hasn't acquired yet (or no longer holds)
    contributes 0 - a known, documented approximation, not a crash."""
    core.strategies.upsert(bot_slug="force", display_name="Force")
    core.allocations.replace(
        bot_slug="force", target_weights={"AAPL": 0.5, "TSLA": 0.5}, current_weights={"AAPL": 1.0}
    )
    alpaca = FakeAlpacaClient(
        equity=10000.0, cash=500.0, positions=[FakePosition("AAPL", current_price=200.0)]  # no TSLA held
    )

    _record_snapshots(core, alpaca)

    [row] = core.bot_values.history("force")
    assert row["value"] == 0.5 * 200.0


def test_skips_bot_value_for_bots_with_no_allocation_yet(core):
    core.strategies.upsert(bot_slug="force", display_name="Force")

    _record_snapshots(core, FakeAlpacaClient(equity=10000.0, cash=500.0))

    assert core.bot_values.history("force") == []


def test_skips_bot_value_when_no_target_symbols_are_held_at_all(core):
    core.strategies.upsert(bot_slug="force", display_name="Force")
    core.allocations.replace(bot_slug="force", target_weights={"TSLA": 1.0}, current_weights={"AAPL": 1.0})

    _record_snapshots(core, FakeAlpacaClient(
        equity=10000.0, cash=500.0, positions=[FakePosition("AAPL", current_price=200.0)]
    ))

    assert core.bot_values.history("force") == []


def test_inactive_bots_are_not_recorded(core):
    core.strategies.upsert(bot_slug="force", display_name="Force", is_active=False)
    core.allocations.replace(bot_slug="force", target_weights={"AAPL": 1.0}, current_weights={"AAPL": 1.0})

    _record_snapshots(core, FakeAlpacaClient(
        equity=10000.0, cash=500.0, positions=[FakePosition("AAPL", current_price=200.0)]
    ))

    assert core.bot_values.history("force") == []


class _FakeActivationClient:
    """Reports not-activated for the first `polls_until_activated` calls,
    then activated - lets a test bound _wait_for_activation's loop by
    reaching real activation rather than needing max_polls."""

    def __init__(self, *, polls_until_activated: int, device_serial: str = "MPB-TEST"):
        self._polls_until_activated = polls_until_activated
        self._device_serial = device_serial
        self.calls = 0

    def check_status(self) -> ActivationStatus:
        self.calls += 1
        activated = self.calls > self._polls_until_activated
        return ActivationStatus(activated=activated, device_serial=self._device_serial)


def test_wait_for_activation_republishes_on_every_poll_not_just_once(core):
    """Regression guard for a real bug found on physical Pi 5 hardware:
    a one-shot publish (the old behavior) is invisible to any consumer
    that starts *after* it was already consumed - display's screen state
    is rebuilt purely by replaying unconsumed device_event rows, and
    consumed_at is a single global flag, not per-consumer (see
    device_core.repositories.device_event.DeviceEventRepository). A
    routine restart of monstrapro-display.service while the device sits
    unactivated silently and permanently dropped the awaiting_activation
    screen back to generic idle. Republishing on every poll means any
    display restart recovers within one poll interval."""
    activation = _FakeActivationClient(polls_until_activated=3)
    sleeps: list[float] = []

    status = _wait_for_activation(core, activation, sleep=sleeps.append, poll_interval_seconds=5.0)

    assert status.activated is True
    assert len(sleeps) == 3  # slept once per not-yet-activated poll

    events = core.events.list_unconsumed(limit=100)
    awaiting_events = [e for e in events if e["type"] == "awaiting_activation"]
    assert len(awaiting_events) == 3  # one per not-yet-activated poll, not just one


def test_wait_for_activation_stops_at_max_polls_while_still_unactivated(core):
    activation = _FakeActivationClient(polls_until_activated=100)

    status = _wait_for_activation(core, activation, sleep=lambda _: None, max_polls=2)

    assert status.activated is False
    assert activation.calls == 2


class _ScriptedActivationClient:
    """Returns each ActivationStatus in `statuses` in order, one per
    check_status() call - lets a test script exactly when a periodic
    recheck flips to deactivated, unlike _FakeActivationClient's
    monotonic not-then-activated shape."""

    def __init__(self, statuses):
        self._statuses = list(statuses)
        self.calls = 0

    def check_status(self):
        self.calls += 1
        if not self._statuses:
            raise AssertionError("check_status called more times than the test expected")
        return self._statuses.pop(0)


def _fail(message):
    def _raiser(*args, **kwargs):
        raise AssertionError(message)

    return _raiser


def test_run_trading_loop_exits_immediately_when_first_recheck_is_deactivated(core, monkeypatch):
    """If the very first recheck already reports deactivated (e.g. the
    device was disconnected right as it entered the trading loop),
    _run_trading_loop must return without touching Alpaca at all."""
    activation = _ScriptedActivationClient([ActivationStatus(activated=False, device_serial="MPB-TEST")])
    monkeypatch.setattr(main_module, "_build_alpaca_client", _fail("must not build an Alpaca client once deactivated"))

    main_module._run_trading_loop(core, activation)

    assert activation.calls == 1


def test_run_trading_loop_returns_once_recheck_reports_deactivated(core, monkeypatch):
    """The core regression this feature closes: a website-side disconnect
    (POST /api/devices/[deviceId]/disconnect) must stop an already-running
    trading loop on its next recheck, not just block a future restart."""
    activation = _ScriptedActivationClient(
        [
            ActivationStatus(activated=True, owner_ref="cust_123", device_serial="MPB-TEST"),
            ActivationStatus(activated=False, device_serial="MPB-TEST"),
        ]
    )
    sleeps: list[float] = []
    monkeypatch.setattr(main_module.time, "sleep", sleeps.append)
    monkeypatch.setattr(main_module, "_build_alpaca_client", lambda core: object())
    monkeypatch.setattr(main_module, "_record_snapshots", lambda core, alpaca: None)
    monkeypatch.setattr(main_module.market_data_provider, "is_market_open", lambda: False)
    monkeypatch.setattr(main_module, "check_run_requested", lambda core: False)

    main_module._run_trading_loop(core, activation)

    assert activation.calls == 2
    assert len(sleeps) == 1  # slept once, after the first (still-activated) tick


def test_run_trading_loop_runs_immediately_on_run_request_even_if_cycle_not_due(core, monkeypatch):
    activation = _ScriptedActivationClient(
        [
            ActivationStatus(activated=True, device_serial="MPB-TEST"),
            ActivationStatus(activated=False, device_serial="MPB-TEST"),
        ]
    )
    monkeypatch.setattr(main_module.time, "sleep", lambda _: None)
    monkeypatch.setattr(main_module, "_build_alpaca_client", lambda core: object())
    monkeypatch.setattr(main_module, "_record_snapshots", lambda core, alpaca: None)
    monkeypatch.setattr(main_module.market_data_provider, "is_market_open", lambda: True)
    monkeypatch.setattr(main_module, "check_run_requested", lambda core: True)
    acked = []
    monkeypatch.setattr(main_module, "ack_run_request", lambda core: acked.append(True))
    ran: list[str] = []
    monkeypatch.setattr(main_module, "reconcile_manual_holdings", lambda core, alpaca: ran.append("reconcile"))
    monkeypatch.setattr(main_module, "run_cycle", lambda core, alpaca: ran.append("cycle"))

    main_module._run_trading_loop(core, activation)

    assert ran == ["reconcile", "cycle"]
    assert acked == [True]


def test_run_trading_loop_syncs_bot_selections_every_tick(core, monkeypatch):
    activation = _ScriptedActivationClient(
        [
            ActivationStatus(activated=True, device_serial="MPB-TEST"),
            ActivationStatus(activated=True, device_serial="MPB-TEST"),
            ActivationStatus(activated=False, device_serial="MPB-TEST"),
        ]
    )
    monkeypatch.setattr(main_module.time, "sleep", lambda _: None)
    monkeypatch.setattr(main_module, "_build_alpaca_client", lambda core: object())
    monkeypatch.setattr(main_module, "_record_snapshots", lambda core, alpaca: None)
    monkeypatch.setattr(main_module.market_data_provider, "is_market_open", lambda: False)
    monkeypatch.setattr(main_module, "check_run_requested", lambda core: False)
    sync_calls = []
    monkeypatch.setattr(main_module, "sync_bot_selections", lambda core: sync_calls.append(True))

    main_module._run_trading_loop(core, activation)

    assert len(sync_calls) == 2  # once per still-activated tick


def test_run_trading_loop_calls_stock_bar_sync(core, monkeypatch):
    activation = _ScriptedActivationClient(
        [ActivationStatus(activated=True, device_serial="MPB-TEST"), ActivationStatus(activated=False, device_serial="MPB-TEST")]
    )
    monkeypatch.setattr(main_module.time, "sleep", lambda _: None)
    monkeypatch.setattr(main_module, "_build_alpaca_client", lambda core: object())
    monkeypatch.setattr(main_module, "_record_snapshots", lambda core, alpaca: None)
    monkeypatch.setattr(main_module.market_data_provider, "is_market_open", lambda: False)
    monkeypatch.setattr(main_module, "check_run_requested", lambda core: False)
    monkeypatch.setattr(main_module, "sync_bot_selections", lambda core: None)
    sync_calls = []
    monkeypatch.setattr(main_module, "sync_stock_bars", lambda core, alpaca: sync_calls.append(True))

    main_module._run_trading_loop(core, activation)

    assert sync_calls == [True]


def test_run_trading_loop_survives_bot_selection_sync_raising(core, monkeypatch):
    """A bug in the sync call (or a raised exception it doesn't itself
    catch) must not take down the whole trading loop."""
    activation = _ScriptedActivationClient(
        [
            ActivationStatus(activated=True, device_serial="MPB-TEST"),
            ActivationStatus(activated=False, device_serial="MPB-TEST"),
        ]
    )
    monkeypatch.setattr(main_module.time, "sleep", lambda _: None)
    monkeypatch.setattr(main_module, "_build_alpaca_client", lambda core: object())
    monkeypatch.setattr(main_module, "_record_snapshots", lambda core, alpaca: None)
    monkeypatch.setattr(main_module.market_data_provider, "is_market_open", lambda: False)
    monkeypatch.setattr(main_module, "check_run_requested", lambda core: False)
    monkeypatch.setattr(main_module, "sync_bot_selections", _fail("boom"))

    main_module._run_trading_loop(core, activation)  # must not raise

    assert activation.calls == 2


def test_run_trading_loop_discards_run_request_when_market_closed(core, monkeypatch):
    """A run-now request is market-hours-gated when made (see
    NextJS_Monsta's POST /api/devices/[deviceId]/run-now), but the market
    can close before this device polls - it must discard the stale request
    rather than run it (or leave it pending until the market reopens)."""
    activation = _ScriptedActivationClient(
        [
            ActivationStatus(activated=True, device_serial="MPB-TEST"),
            ActivationStatus(activated=False, device_serial="MPB-TEST"),
        ]
    )
    monkeypatch.setattr(main_module.time, "sleep", lambda _: None)
    monkeypatch.setattr(main_module, "_build_alpaca_client", lambda core: object())
    monkeypatch.setattr(main_module, "_record_snapshots", lambda core, alpaca: None)
    monkeypatch.setattr(main_module.market_data_provider, "is_market_open", lambda: False)
    monkeypatch.setattr(main_module, "check_run_requested", lambda core: True)
    acked = []
    monkeypatch.setattr(main_module, "ack_run_request", lambda core: acked.append(True))
    monkeypatch.setattr(main_module, "reconcile_manual_holdings", _fail("must not run while market is closed"))
    monkeypatch.setattr(main_module, "run_cycle", _fail("must not run while market is closed"))

    main_module._run_trading_loop(core, activation)

    assert acked == [True]  # discarded, not left pending until the market reopens


# --- Hourly trading-cycle schedule ------------------------------------------


def test_scheduled_cycle_times_are_hourly_at_five_past_except_the_last(core):
    """Owner-requested behavior: once an hour, 5 minutes after the hour,
    except the final hour before close, which runs 20 minutes before close
    instead so the last cycle of the day has room to actually finish."""
    schedule = scheduled_cycle_times_et(date(2026, 8, 4))  # a plain trading day

    assert [t.strftime("%H:%M") for t in schedule] == [
        "10:05", "11:05", "12:05", "13:05", "14:05", "15:40",
    ]
    assert all(t.tzinfo is not None for t in schedule)


def test_latest_due_cycle_time_picks_the_most_recently_passed_slot():
    schedule = scheduled_cycle_times_et(date(2026, 8, 4))

    before_open = datetime(2026, 8, 4, 9, 45, tzinfo=MARKET_TIMEZONE)
    assert _latest_due_cycle_time(before_open, schedule) is None

    mid_slot = datetime(2026, 8, 4, 11, 30, tzinfo=MARKET_TIMEZONE)
    assert _latest_due_cycle_time(mid_slot, schedule) == schedule[1]  # 11:05, not 12:05 yet

    right_at_close = datetime(2026, 8, 4, 15, 59, tzinfo=MARKET_TIMEZONE)
    assert _latest_due_cycle_time(right_at_close, schedule) == schedule[-1]  # 15:40


class _FixedDatetime(datetime):
    """Subclasses the real datetime so datetime.combine/arithmetic inside
    scheduled_cycle_times_et still works normally - only .now() is
    overridden, letting a test pin main.py's wall-clock read without
    touching the real system clock."""

    _fixed_now: datetime

    @classmethod
    def now(cls, tz=None):
        return cls._fixed_now


def _patch_now(monkeypatch, fixed_now: datetime):
    fixed = type("_Fixed", (_FixedDatetime,), {"_fixed_now": fixed_now})
    monkeypatch.setattr(main_module, "datetime", fixed)


def test_run_trading_loop_does_not_fire_before_the_first_scheduled_slot(core, monkeypatch):
    from trading_worker.activation import ActivationStatus as _Status

    activation = _ScriptedActivationClient(
        [_Status(activated=True, device_serial="MPB-TEST"), _Status(activated=False, device_serial="MPB-TEST")]
    )
    monkeypatch.setattr(main_module.time, "sleep", lambda _: None)
    monkeypatch.setattr(main_module, "_build_alpaca_client", lambda core: object())
    monkeypatch.setattr(main_module, "_record_snapshots", lambda core, alpaca: None)
    monkeypatch.setattr(main_module, "sync_bot_selections", lambda core: None)
    monkeypatch.setattr(main_module.market_data_provider, "is_market_open", lambda: True)
    monkeypatch.setattr(main_module, "check_run_requested", lambda core: False)
    ran = []
    monkeypatch.setattr(main_module, "reconcile_manual_holdings", lambda core, alpaca: ran.append("reconcile"))
    monkeypatch.setattr(main_module, "run_cycle", lambda core, alpaca: ran.append("cycle"))
    _patch_now(monkeypatch, datetime(2026, 8, 4, 9, 45, tzinfo=MARKET_TIMEZONE))  # before 10:05

    main_module._run_trading_loop(core, activation)

    assert ran == []


def test_run_trading_loop_fires_once_at_a_scheduled_slot_then_not_again(core, monkeypatch):
    from trading_worker.activation import ActivationStatus as _Status

    activation = _ScriptedActivationClient(
        [
            _Status(activated=True, device_serial="MPB-TEST"),
            _Status(activated=True, device_serial="MPB-TEST"),
            _Status(activated=False, device_serial="MPB-TEST"),
        ]
    )
    monkeypatch.setattr(main_module.time, "sleep", lambda _: None)
    monkeypatch.setattr(main_module, "_build_alpaca_client", lambda core: object())
    monkeypatch.setattr(main_module, "_record_snapshots", lambda core, alpaca: None)
    monkeypatch.setattr(main_module, "sync_bot_selections", lambda core: None)
    monkeypatch.setattr(main_module.market_data_provider, "is_market_open", lambda: True)
    monkeypatch.setattr(main_module, "check_run_requested", lambda core: False)
    ran = []
    monkeypatch.setattr(main_module, "reconcile_manual_holdings", lambda core, alpaca: ran.append("reconcile"))
    monkeypatch.setattr(main_module, "run_cycle", lambda core, alpaca: ran.append("cycle"))
    # Both still-activated ticks land within the same 10:05 slot (10:06, 10:07) -
    # the cycle must run on the first tick only, not the second.
    _patch_now(monkeypatch, datetime(2026, 8, 4, 10, 6, tzinfo=MARKET_TIMEZONE))

    main_module._run_trading_loop(core, activation)

    assert ran == ["reconcile", "cycle"]
