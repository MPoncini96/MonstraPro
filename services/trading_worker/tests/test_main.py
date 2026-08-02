from trading_worker.main import _record_snapshots


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
