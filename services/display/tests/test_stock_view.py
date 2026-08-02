from display.stock_view import build_stock_view, top_movers


def _record_position(core, symbol, *, current_price=100.0, unrealized_plpc=0.0, unrealized_intraday_plpc=0.0):
    core.positions.record(
        symbol=symbol, qty=10.0, avg_entry_price=100.0, current_price=current_price,
        market_value=current_price * 10, unrealized_pl=(current_price - 100.0) * 10,
        unrealized_plpc=unrealized_plpc, unrealized_intraday_plpc=unrealized_intraday_plpc,
    )


class TestTopMovers:
    def test_no_positions_returns_empty_list(self, core):
        assert top_movers(core) == []

    def test_ranks_by_absolute_intraday_move_descending(self, core):
        _record_position(core, "AAPL", unrealized_intraday_plpc=0.01)
        _record_position(core, "TSLA", unrealized_intraday_plpc=-0.08)
        _record_position(core, "MSFT", unrealized_intraday_plpc=0.03)

        assert top_movers(core) == ["TSLA", "MSFT", "AAPL"]

    def test_limited_to_requested_count(self, core):
        for i, symbol in enumerate(["AAPL", "TSLA", "MSFT", "NVDA"]):
            _record_position(core, symbol, unrealized_intraday_plpc=0.01 * (i + 1))

        assert len(top_movers(core, limit=3)) == 3


class TestBuildStockView:
    def test_unknown_symbol_has_no_pl_and_no_candles(self, core):
        view = build_stock_view(core, "AAPL")

        assert view.symbol == "AAPL"
        assert view.unrealized_plpc is None
        assert view.candles == []

    def test_includes_unrealized_plpc_and_price_candles(self, core):
        _record_position(core, "AAPL", current_price=150.0, unrealized_plpc=0.05)
        _record_position(core, "AAPL", current_price=155.0, unrealized_plpc=0.083)

        view = build_stock_view(core, "AAPL")

        assert view.unrealized_plpc == 0.083
        assert len(view.candles) >= 1
        assert view.candles[-1].close == 155.0
