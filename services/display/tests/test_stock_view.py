from display.stock_view import SLIDE_LABELS, SLIDES, build_stock_view, selected_symbols

_BARS = [
    {"ts": "2026-08-04T09:00:00+00:00", "open": 100.0, "high": 105.0, "low": 99.0, "close": 102.0},
    {"ts": "2026-08-04T10:00:00+00:00", "open": 102.0, "high": 108.0, "low": 101.0, "close": 106.0},
]


def test_selected_symbols_reflects_the_market_data_cache(core):
    assert selected_symbols(core) == []

    core.market_data.save(symbol="AAPL", slide="1h", bars=_BARS)
    core.market_data.save(symbol="MSFT", slide="1h", bars=_BARS)

    assert selected_symbols(core) == ["AAPL", "MSFT"]


def test_build_stock_view_for_uncached_symbol_has_no_candles_or_change(core):
    view = build_stock_view(core, "AAPL", "1h")

    assert view.symbol == "AAPL"
    assert view.slide == "1h"
    assert view.slide_label == "Last hour"
    assert view.candles == []
    assert view.pct_change is None
    assert view.fetched_at is None
    assert view.portfolio_weight is None
    assert view.owned_by == []


def test_portfolio_weight_is_market_value_over_account_equity(core):
    core.account_snapshots.record(equity=1000.0, cash=0.0)
    core.positions.record(
        symbol="AAPL",
        qty=1,
        avg_entry_price=180.0,
        current_price=180.0,
        market_value=180.0,
        unrealized_pl=0.0,
        unrealized_plpc=0.0,
        unrealized_intraday_plpc=0.0,
    )

    view = build_stock_view(core, "AAPL", "1h")

    assert view.portfolio_weight == 0.18


def test_owned_by_lists_active_bots_currently_targeting_the_symbol(core):
    core.strategies.upsert(bot_slug="force", display_name="Force")
    core.allocations.replace(bot_slug="force", target_weights={"AAPL": 1.0}, current_weights={})
    core.strategies.upsert(bot_slug="aptet", display_name="Aptet")
    core.allocations.replace(bot_slug="aptet", target_weights={"MSFT": 1.0}, current_weights={})

    view = build_stock_view(core, "AAPL", "1h")

    assert view.owned_by == ["Force"]


def test_build_stock_view_converts_cached_bars_to_candles(core):
    core.market_data.save(symbol="AAPL", slide="1h", bars=_BARS)

    view = build_stock_view(core, "AAPL", "1h")

    assert len(view.candles) == 2
    assert view.candles[0].open == 100.0
    assert view.candles[-1].close == 106.0
    assert view.fetched_at is not None


def test_build_stock_view_computes_pct_change_from_first_open_to_last_close(core):
    core.market_data.save(symbol="AAPL", slide="1h", bars=_BARS)

    view = build_stock_view(core, "AAPL", "1h")

    assert view.pct_change == (106.0 - 100.0) / 100.0


def test_each_slide_has_a_distinct_label():
    assert SLIDE_LABELS.keys() == set(SLIDES)
    assert len(set(SLIDE_LABELS.values())) == len(SLIDES)


def test_build_stock_view_reads_the_requested_slide_independently(core):
    core.market_data.save(symbol="AAPL", slide="1h", bars=_BARS)
    core.market_data.save(symbol="AAPL", slide="1y", bars=[])

    hour_view = build_stock_view(core, "AAPL", "1h")
    year_view = build_stock_view(core, "AAPL", "1y")

    assert len(hour_view.candles) == 2
    assert year_view.candles == []
    assert year_view.slide_label == "Last year"
