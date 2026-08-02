from display.last_trade import build_last_trade


def test_no_orders_returns_none(core):
    assert build_last_trade(core) is None


def test_order_without_a_matching_position_has_no_pl(core):
    core.orders.record(bot_slug="force", symbol="AAPL", side="buy", notional=500.0, status="filled")

    trade = build_last_trade(core)

    assert trade.symbol == "AAPL"
    assert trade.side == "buy"
    assert trade.notional == 500.0
    assert trade.unrealized_pl is None
    assert trade.unrealized_plpc is None


def test_order_with_a_currently_held_position_includes_unrealized_pl(core):
    core.orders.record(bot_slug="force", symbol="AAPL", side="buy", notional=500.0, status="filled")
    core.positions.record(
        symbol="AAPL", qty=10.0, avg_entry_price=50.0, current_price=55.0, market_value=550.0,
        unrealized_pl=50.0, unrealized_plpc=0.1, unrealized_intraday_plpc=0.02,
    )

    trade = build_last_trade(core)

    assert trade.unrealized_pl == 50.0
    assert trade.unrealized_plpc == 0.1


def test_uses_the_most_recently_submitted_order_across_all_bots(core):
    core.orders.record(bot_slug="force", symbol="AAPL", side="buy", notional=500.0, status="filled")
    core.orders.record(bot_slug="aptet", symbol="MSFT", side="sell", notional=300.0, status="filled")

    trade = build_last_trade(core)

    assert trade.symbol == "MSFT"
    assert trade.side == "sell"
