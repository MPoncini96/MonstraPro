from device_core.db.session import Database
from device_core.repositories.market_data_cache import MarketDataCacheRepository

_BARS = [{"ts": "2026-08-04T10:00:00Z", "open": 1.0, "high": 1.1, "low": 0.9, "close": 1.05}]


def test_save_and_get_round_trip(config):
    repo = MarketDataCacheRepository(Database(config))

    repo.save(symbol="AAPL", slide="1h", bars=_BARS)

    row = repo.get("AAPL", "1h")
    assert row["bars_json"] == _BARS
    assert row["fetched_at"] is not None


def test_get_returns_none_for_unknown_symbol_slide(config):
    repo = MarketDataCacheRepository(Database(config))
    assert repo.get("AAPL", "1h") is None


def test_save_is_idempotent_per_symbol_and_slide(config):
    db = Database(config)
    repo = MarketDataCacheRepository(db)

    repo.save(symbol="AAPL", slide="1h", bars=_BARS)
    repo.save(symbol="AAPL", slide="1h", bars=[{"ts": "2026-08-04T11:00:00Z", "open": 2, "high": 2, "low": 2, "close": 2}])

    row = repo.get("AAPL", "1h")
    assert row["bars_json"][0]["open"] == 2

    from device_core.db.models import MarketDataCache

    with db.session() as session:
        assert session.query(MarketDataCache).filter_by(symbol="AAPL", slide="1h").count() == 1


def test_save_treats_different_slides_independently(config):
    repo = MarketDataCacheRepository(Database(config))

    repo.save(symbol="AAPL", slide="1h", bars=_BARS)
    repo.save(symbol="AAPL", slide="1y", bars=[])

    assert repo.get("AAPL", "1h")["bars_json"] == _BARS
    assert repo.get("AAPL", "1y")["bars_json"] == []


def test_list_symbols_returns_distinct_symbols_oldest_first(config):
    repo = MarketDataCacheRepository(Database(config))

    repo.save(symbol="AAPL", slide="1h", bars=_BARS)
    repo.save(symbol="AAPL", slide="1d", bars=_BARS)  # same symbol, different slide - not a new symbol
    repo.save(symbol="MSFT", slide="1h", bars=_BARS)

    assert repo.list_symbols() == ["AAPL", "MSFT"]


def test_replace_selection_drops_deselected_symbols(config):
    repo = MarketDataCacheRepository(Database(config))
    repo.save(symbol="AAPL", slide="1h", bars=_BARS)
    repo.save(symbol="MSFT", slide="1h", bars=_BARS)
    repo.save(symbol="NVDA", slide="1h", bars=_BARS)

    repo.replace_selection({"AAPL", "NVDA"})

    assert repo.list_symbols() == ["AAPL", "NVDA"]
    assert repo.get("MSFT", "1h") is None


def test_replace_selection_with_empty_set_clears_everything(config):
    repo = MarketDataCacheRepository(Database(config))
    repo.save(symbol="AAPL", slide="1h", bars=_BARS)

    repo.replace_selection(set())

    assert repo.list_symbols() == []
