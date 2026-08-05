from datetime import datetime, timezone

import pytest

import trading_worker.alpaca_client as alpaca_client_module
from trading_worker.alpaca_client import AlpacaClient


class _FakeAccount:
    equity = "1234.56"
    cash = "500.00"


class _FakePosition:
    def __init__(
        self,
        symbol,
        market_value,
        *,
        qty="10",
        avg_entry_price="150.00",
        current_price="155.00",
        unrealized_pl="50.00",
        unrealized_plpc="0.0333",
        unrealized_intraday_plpc="0.012",
    ):
        self.symbol = symbol
        self.market_value = market_value
        self.qty = qty
        self.avg_entry_price = avg_entry_price
        self.current_price = current_price
        self.unrealized_pl = unrealized_pl
        self.unrealized_plpc = unrealized_plpc
        self.unrealized_intraday_plpc = unrealized_intraday_plpc


class _FakeOrder:
    class _Status:
        value = "accepted"

    id = "abc-123"
    status = _Status()

    def model_dump(self, mode="json"):
        return {"id": "abc-123", "status": "accepted"}


class _FakeTradingClient:
    captured_paper_flags = []

    def __init__(self, api_key, api_secret, paper):
        self.api_key = api_key
        self.api_secret = api_secret
        self.paper = paper
        _FakeTradingClient.captured_paper_flags.append(paper)

    def get_account(self):
        return _FakeAccount()

    def get_all_positions(self):
        return [_FakePosition("AAPL", "150.00"), _FakePosition("MSFT", "300.00")]

    def submit_order(self, request):
        self.last_request = request
        return _FakeOrder()


class _FakeBar:
    def __init__(self, ts, open_, high, low, close):
        self.timestamp = ts
        self.open = open_
        self.high = high
        self.low = low
        self.close = close


class _FakeBarSet:
    def __init__(self, data):
        self.data = data


class _FakeStockHistoricalDataClient:
    last_request = None

    def __init__(self, api_key, api_secret):
        self.api_key = api_key
        self.api_secret = api_secret

    def get_stock_bars(self, request):
        _FakeStockHistoricalDataClient.last_request = request
        ts = datetime(2026, 8, 4, 10, 0, tzinfo=timezone.utc)
        return _FakeBarSet({"AAPL": [_FakeBar(ts, "1.0", "1.1", "0.9", "1.05")]})


@pytest.fixture(autouse=True)
def _patch_trading_client(monkeypatch):
    _FakeTradingClient.captured_paper_flags = []
    monkeypatch.setattr(alpaca_client_module, "TradingClient", _FakeTradingClient)
    monkeypatch.setattr(alpaca_client_module, "StockHistoricalDataClient", _FakeStockHistoricalDataClient)


def test_paper_base_url_sets_paper_flag_true():
    AlpacaClient(api_key="k", api_secret="s", base_url="https://paper-api.alpaca.markets")
    assert _FakeTradingClient.captured_paper_flags == [True]


def test_live_base_url_sets_paper_flag_false():
    AlpacaClient(api_key="k", api_secret="s", base_url="https://api.alpaca.markets")
    assert _FakeTradingClient.captured_paper_flags == [False]


def test_get_account_converts_to_floats():
    client = AlpacaClient(api_key="k", api_secret="s", base_url="https://paper-api.alpaca.markets")
    snapshot = client.get_account()
    assert snapshot.equity == pytest.approx(1234.56)
    assert snapshot.cash == pytest.approx(500.00)


def test_list_position_values_returns_symbol_to_market_value():
    client = AlpacaClient(api_key="k", api_secret="s", base_url="https://paper-api.alpaca.markets")
    assert client.list_position_values() == {"AAPL": 150.0, "MSFT": 300.0}


def test_list_positions_returns_position_info_with_unrealized_pl():
    client = AlpacaClient(api_key="k", api_secret="s", base_url="https://paper-api.alpaca.markets")

    positions = client.list_positions()

    assert [p.symbol for p in positions] == ["AAPL", "MSFT"]
    aapl = positions[0]
    assert aapl.qty == pytest.approx(10.0)
    assert aapl.avg_entry_price == pytest.approx(150.0)
    assert aapl.current_price == pytest.approx(155.0)
    assert aapl.market_value == pytest.approx(150.0)
    assert aapl.unrealized_pl == pytest.approx(50.0)
    assert aapl.unrealized_plpc == pytest.approx(0.0333)
    assert aapl.unrealized_intraday_plpc == pytest.approx(0.012)


def test_submit_order_requires_exactly_one_of_qty_or_notional():
    client = AlpacaClient(api_key="k", api_secret="s", base_url="https://paper-api.alpaca.markets")
    with pytest.raises(ValueError):
        client.submit_order(symbol="AAPL", side="buy")
    with pytest.raises(ValueError):
        client.submit_order(symbol="AAPL", side="buy", qty=1.0, notional=100.0)


def test_submit_order_returns_order_result():
    client = AlpacaClient(api_key="k", api_secret="s", base_url="https://paper-api.alpaca.markets")
    result = client.submit_order(symbol="AAPL", side="buy", notional=100.0)
    assert result.alpaca_order_id == "abc-123"
    assert result.status == "accepted"
    assert result.raw == {"id": "abc-123", "status": "accepted"}


def test_get_bars_converts_to_floats():
    from alpaca.data.timeframe import TimeFrame

    client = AlpacaClient(api_key="k", api_secret="s", base_url="https://paper-api.alpaca.markets")
    start = datetime(2026, 8, 4, 9, 0, tzinfo=timezone.utc)
    end = datetime(2026, 8, 4, 10, 0, tzinfo=timezone.utc)

    bars = client.get_bars("AAPL", timeframe=TimeFrame.Minute, start=start, end=end)

    assert len(bars) == 1
    assert bars[0].open == pytest.approx(1.0)
    assert bars[0].high == pytest.approx(1.1)
    assert bars[0].low == pytest.approx(0.9)
    assert bars[0].close == pytest.approx(1.05)
    assert bars[0].ts == datetime(2026, 8, 4, 10, 0, tzinfo=timezone.utc)


def test_get_bars_returns_empty_list_for_unknown_symbol():
    from alpaca.data.timeframe import TimeFrame

    client = AlpacaClient(api_key="k", api_secret="s", base_url="https://paper-api.alpaca.markets")
    start = datetime(2026, 8, 4, 9, 0, tzinfo=timezone.utc)
    end = datetime(2026, 8, 4, 10, 0, tzinfo=timezone.utc)

    assert client.get_bars("NOSYMBOL", timeframe=TimeFrame.Minute, start=start, end=end) == []


def test_get_bars_builds_request_with_given_symbol_timeframe_and_window():
    from alpaca.data.timeframe import TimeFrame

    client = AlpacaClient(api_key="k", api_secret="s", base_url="https://paper-api.alpaca.markets")
    start = datetime(2026, 8, 4, 9, 0, tzinfo=timezone.utc)
    end = datetime(2026, 8, 4, 10, 0, tzinfo=timezone.utc)

    client.get_bars("AAPL", timeframe=TimeFrame.Day, start=start, end=end, limit=5)

    request = _FakeStockHistoricalDataClient.last_request
    assert request.symbol_or_symbols == "AAPL"
    assert request.timeframe.value == TimeFrame.Day.value
    # StockBarsRequest's pydantic validation strips tzinfo internally -
    # compare naive equivalents rather than the exact tz-aware inputs.
    assert request.start == start.replace(tzinfo=None)
    assert request.end == end.replace(tzinfo=None)
    assert request.limit == 5
