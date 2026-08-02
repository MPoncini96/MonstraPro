from datetime import datetime, timezone

from display.snapshot import as_utc, _today_pl, build_snapshot, is_market_open_heuristic


def _snap(equity: float, ts: datetime) -> dict:
    return {"equity": equity, "cash": 0.0, "ts": ts}


class TestAsUtc:
    def test_naive_datetime_is_treated_as_already_utc(self):
        # This is the actual shape SQLAlchemy hands back for a
        # DateTime(timezone=True) column read from SQLite: naive, but the
        # value itself was always UTC (see AccountSnapshot's `utcnow` default).
        naive = datetime(2026, 1, 5, 12, 0, 0)
        assert as_utc(naive) == datetime(2026, 1, 5, 12, 0, 0, tzinfo=timezone.utc)

    def test_aware_datetime_is_converted_not_reinterpreted(self):
        from datetime import timedelta

        est = timezone(timedelta(hours=-5))
        aware = datetime(2026, 1, 5, 7, 0, 0, tzinfo=est)
        assert as_utc(aware) == datetime(2026, 1, 5, 12, 0, 0, tzinfo=timezone.utc)


class TestTodayPl:
    def test_returns_none_with_no_snapshots(self):
        assert _today_pl([], today=datetime(2026, 1, 5, tzinfo=timezone.utc).date()) is None

    def test_returns_none_with_only_one_same_day_snapshot(self):
        today = datetime(2026, 1, 5, tzinfo=timezone.utc).date()
        snapshots = [_snap(1000.0, datetime(2026, 1, 5, 15, 0, tzinfo=timezone.utc))]
        assert _today_pl(snapshots, today=today) is None

    def test_computes_difference_between_latest_and_earliest_same_day(self):
        today = datetime(2026, 1, 5, tzinfo=timezone.utc).date()
        snapshots = [
            _snap(1050.0, datetime(2026, 1, 5, 20, 0, tzinfo=timezone.utc)),  # newest first
            _snap(1020.0, datetime(2026, 1, 5, 15, 0, tzinfo=timezone.utc)),
            _snap(1000.0, datetime(2026, 1, 5, 10, 0, tzinfo=timezone.utc)),  # earliest today
            _snap(950.0, datetime(2026, 1, 4, 20, 0, tzinfo=timezone.utc)),  # yesterday, excluded
        ]
        assert _today_pl(snapshots, today=today) == 50.0  # 1050 - 1000


class TestIsMarketOpenHeuristic:
    def test_weekday_during_session_hours_is_open(self):
        # 2026-01-05 is a Monday
        now = datetime(2026, 1, 5, 15, 0, tzinfo=timezone.utc)  # ~10:00 ET
        assert is_market_open_heuristic(now=now) is True

    def test_weekday_outside_session_hours_is_closed(self):
        now = datetime(2026, 1, 5, 3, 0, tzinfo=timezone.utc)  # ~22:00 ET the prior day
        assert is_market_open_heuristic(now=now) is False

    def test_weekend_is_closed(self):
        now = datetime(2026, 1, 3, 15, 0, tzinfo=timezone.utc)  # Saturday
        assert is_market_open_heuristic(now=now) is False


class TestBuildSnapshot:
    def test_empty_state_returns_mostly_empty_snapshot(self, core):
        snapshot = build_snapshot(core)

        assert snapshot.portfolio_equity is None
        assert snapshot.last_sync_at is None
        assert snapshot.bots == []
        assert snapshot.recent_orders == []

    def test_includes_active_bots_signals_and_orders(self, core):
        core.strategies.upsert(bot_slug="force", display_name="Force")
        core.signals.store(bot_id="force", bot_type="alpha1", signal="REBALANCE", note="top=AAPL")
        core.allocations.replace(bot_slug="force", target_weights={"AAPL": 1.0}, current_weights={})
        core.orders.record(bot_slug="force", symbol="AAPL", side="buy", notional=500.0, status="accepted")
        core.account_snapshots.record(equity=1000.0, cash=500.0)

        snapshot = build_snapshot(core)

        assert snapshot.portfolio_equity == 1000.0
        [bot] = snapshot.bots
        assert bot.bot_slug == "force"
        assert bot.latest_signal == "REBALANCE"
        assert bot.target_weights == {"AAPL": 1.0}
        assert len(snapshot.recent_orders) == 1

    def test_inactive_bots_are_excluded(self, core):
        core.strategies.upsert(bot_slug="force", is_active=False)

        snapshot = build_snapshot(core)

        assert snapshot.bots == []

    def test_candles_are_built_from_account_snapshot_history(self, core):
        core.account_snapshots.record(equity=9800.0, cash=200.0)
        core.account_snapshots.record(equity=10250.75, cash=150.0)

        snapshot = build_snapshot(core)

        # Both rows are recorded within the same test run, so they almost
        # always land in one bucket - but not asserting on the exact bucket
        # count avoids a one-in-a-few-hundred flake right at a 5-minute
        # boundary. What must always hold regardless: the most recent
        # equity value is the last candle's close.
        assert len(snapshot.candles) >= 1
        assert snapshot.candles[-1].close == 10250.75

    def test_pl_today_and_last_sync_at_use_real_db_timestamps(self, core):
        # Regression test: AccountSnapshotRepository returns naive
        # datetimes from SQLite (see TestAsUtc) - build_snapshot must
        # normalize them before comparing dates, or pl_today/last_sync_at
        # silently break depending on the host machine's local timezone.
        core.account_snapshots.record(equity=9800.0, cash=200.0)
        core.account_snapshots.record(equity=10250.75, cash=150.0)

        snapshot = build_snapshot(core)

        assert snapshot.portfolio_pl_today == 450.75
        assert snapshot.last_sync_at.tzinfo is not None
