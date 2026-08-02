from trading_worker.alpaca_client import OrderResult
from trading_worker.manual_holdings import reconcile_manual_holdings


class FakePosition:
    def __init__(self, symbol, qty):
        self.symbol = symbol
        self.qty = qty


class FakeAlpacaClient:
    def __init__(self, positions=None):
        self._positions = positions or []
        self.submitted_orders = []

    def list_positions(self):
        return self._positions

    def submit_order(self, *, symbol, side, qty=None, notional=None):
        self.submitted_orders.append({"symbol": symbol, "side": side, "qty": qty, "notional": notional})
        return OrderResult(alpaca_order_id=f"order-{len(self.submitted_orders)}", status="accepted", raw={})


def test_no_holdings_does_nothing(core):
    alpaca = FakeAlpacaClient()
    assert reconcile_manual_holdings(core, alpaca) == []
    assert alpaca.submitted_orders == []


def test_buys_the_full_shortfall_when_nothing_is_held_yet(core):
    core.manual_holdings.add(symbol="AAPL", target_qty=10.0)
    alpaca = FakeAlpacaClient(positions=[])

    reconcile_manual_holdings(core, alpaca)

    assert alpaca.submitted_orders == [{"symbol": "AAPL", "side": "buy", "qty": 10.0, "notional": None}]
    [order] = core.orders.recent(bot_slug="manual")
    assert order["symbol"] == "AAPL"
    assert order["qty"] == 10.0


def test_buys_only_the_remaining_shortfall_when_partially_held(core):
    core.manual_holdings.add(symbol="AAPL", target_qty=10.0)
    alpaca = FakeAlpacaClient(positions=[FakePosition("AAPL", 6.0)])

    reconcile_manual_holdings(core, alpaca)

    assert alpaca.submitted_orders == [{"symbol": "AAPL", "side": "buy", "qty": 4.0, "notional": None}]


def test_no_order_once_target_quantity_is_already_held(core):
    core.manual_holdings.add(symbol="AAPL", target_qty=10.0)
    alpaca = FakeAlpacaClient(positions=[FakePosition("AAPL", 10.0)])

    result = reconcile_manual_holdings(core, alpaca)

    assert result == []
    assert alpaca.submitted_orders == []


def test_never_sells_even_if_overheld(core):
    """Reconciliation is one-directional - if more shares are held than
    target_qty (e.g. the owner bought extra manually in the Alpaca app),
    nothing here ever sells to correct it."""
    core.manual_holdings.add(symbol="AAPL", target_qty=5.0)
    alpaca = FakeAlpacaClient(positions=[FakePosition("AAPL", 12.0)])

    result = reconcile_manual_holdings(core, alpaca)

    assert result == []
    assert alpaca.submitted_orders == []


def test_multiple_holdings_are_each_reconciled_independently(core):
    core.manual_holdings.add(symbol="AAPL", target_qty=10.0)
    core.manual_holdings.add(symbol="TSLA", target_qty=3.0)
    alpaca = FakeAlpacaClient(positions=[FakePosition("AAPL", 10.0)])  # AAPL already satisfied

    reconcile_manual_holdings(core, alpaca)

    assert alpaca.submitted_orders == [{"symbol": "TSLA", "side": "buy", "qty": 3.0, "notional": None}]
