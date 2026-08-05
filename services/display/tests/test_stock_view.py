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
