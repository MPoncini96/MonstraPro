from datetime import datetime, timezone

import pytest

from trading_worker.alpaca_client import Bar, PositionInfo
from trading_worker.stock_bar_sync import SLIDE_SPECS, select_symbols_to_track, sync_stock_bars


def _position(symbol, *, market_value=0.0, unrealized_intraday_plpc=0.0):
    return PositionInfo(
        symbol=symbol,
        qty=1.0,
        avg_entry_price=1.0,
        current_price=1.0,
        market_value=market_value,
        unrealized_pl=0.0,
        unrealized_plpc=0.0,
        unrealized_intraday_plpc=unrealized_intraday_plpc,
    )


class FakeAlpacaClient:
    def __init__(self, positions):
        self._positions = positions
        self.bar_calls = []

    def list_positions(self):
        return list(self._positions)

    def get_bars(self, symbol, *, timeframe, start, end, limit=None):
        self.bar_calls.append((symbol, timeframe, start, end))
        return [Bar(ts=datetime(2026, 8, 4, tzinfo=timezone.utc), open=1.0, high=1.0, low=1.0, close=1.0)]


def test_select_symbols_picks_top_3_by_position_and_top_2_by_movement():
    positions = [
        _position("BIG", market_value=1000.0, unrealized_intraday_plpc=0.001),
        _position("MED", market_value=500.0, unrealized_intraday_plpc=0.002),
        _position("SMALL", market_value=100.0, unrealized_intraday_plpc=0.003),
        _position("MOVER1", market_value=10.0, unrealized_intraday_plpc=-0.20),
        _position("MOVER2", market_value=5.0, unrealized_intraday_plpc=0.15),
        _position("QUIET", market_value=1.0, unrealized_intraday_plpc=0.001),
    ]

    selected = select_symbols_to_track(FakeAlpacaClient(positions))

    assert selected == ["BIG", "MED", "SMALL", "MOVER1", "MOVER2"]


def test_select_symbols_does_not_double_count_a_symbol_in_both_categories():
    """A symbol that's both a top-3 position AND the biggest mover must not
    take up two of the five slots - the next-biggest mover fills the gap
    instead."""
    positions = [
        _position("BIG", market_value=1000.0, unrealized_intraday_plpc=0.50),  # top position AND biggest mover
        _position("MED", market_value=500.0, unrealized_intraday_plpc=0.01),
        _position("SMALL", market_value=100.0, unrealized_intraday_plpc=0.01),
        _position("MOVER1", market_value=1.0, unrealized_intraday_plpc=0.20),
        _position("MOVER2", market_value=1.0, unrealized_intraday_plpc=0.10),
    ]

    selected = select_symbols_to_track(FakeAlpacaClient(positions))

    assert selected == ["BIG", "MED", "SMALL", "MOVER1", "MOVER2"]
    assert len(set(selected)) == 5


def test_select_symbols_handles_fewer_than_five_positions():
    positions = [_position("ONLY", market_value=100.0, unrealized_intraday_plpc=0.01)]

    assert select_symbols_to_track(FakeAlpacaClient(positions)) == ["ONLY"]


def test_select_symbols_handles_no_positions():
    assert select_symbols_to_track(FakeAlpacaClient([])) == []


def test_sync_stock_bars_caches_all_three_slides_per_selected_symbol(core):
    alpaca = FakeAlpacaClient([_position("AAPL", market_value=100.0, unrealized_intraday_plpc=0.01)])

    selected = sync_stock_bars(core, alpaca)

    assert selected == ["AAPL"]
    for slide in SLIDE_SPECS:
        cached = core.market_data.get("AAPL", slide)
        assert cached is not None
        assert cached["bars_json"][0]["close"] == pytest.approx(1.0)
    assert len(alpaca.bar_calls) == len(SLIDE_SPECS)


def test_sync_stock_bars_prunes_previously_cached_symbols_no_longer_selected(core):
    alpaca = FakeAlpacaClient([_position("AAPL", market_value=100.0)])
    sync_stock_bars(core, alpaca)
    assert core.market_data.list_symbols() == ["AAPL"]

    alpaca_next = FakeAlpacaClient([_position("MSFT", market_value=100.0)])
    sync_stock_bars(core, alpaca_next)

    assert core.market_data.list_symbols() == ["MSFT"]


def test_sync_stock_bars_survives_a_single_symbols_fetch_failure(core):
    class FlakyAlpacaClient(FakeAlpacaClient):
        def get_bars(self, symbol, *, timeframe, start, end, limit=None):
            if symbol == "BAD":
                raise RuntimeError("boom")
            return super().get_bars(symbol, timeframe=timeframe, start=start, end=end, limit=limit)

    alpaca = FlakyAlpacaClient(
        [_position("BAD", market_value=200.0), _position("GOOD", market_value=100.0)]
    )

    selected = sync_stock_bars(core, alpaca)

    assert selected == ["BAD", "GOOD"]
    assert core.market_data.get("BAD", "1h") is None
    assert core.market_data.get("GOOD", "1h") is not None
