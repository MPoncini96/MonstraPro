import pytest

from device_core.db.session import Database
from device_core.repositories.manual_holding import ManualHoldingRepository


def test_add_returns_the_row(config):
    repo = ManualHoldingRepository(Database(config))

    row = repo.add(symbol="AAPL", target_qty=10.0)

    assert row["symbol"] == "AAPL"
    assert row["target_qty"] == 10.0


def test_add_rejects_non_positive_quantity(config):
    repo = ManualHoldingRepository(Database(config))

    with pytest.raises(ValueError):
        repo.add(symbol="AAPL", target_qty=0)
    with pytest.raises(ValueError):
        repo.add(symbol="AAPL", target_qty=-5)


def test_add_is_idempotent_per_symbol_updates_target_qty(config):
    repo = ManualHoldingRepository(Database(config))
    repo.add(symbol="AAPL", target_qty=10.0)

    repo.add(symbol="AAPL", target_qty=25.0)

    holdings = repo.list_all()
    assert len(holdings) == 1
    assert holdings[0]["target_qty"] == 25.0


def test_list_all_is_sorted_by_symbol(config):
    repo = ManualHoldingRepository(Database(config))
    repo.add(symbol="TSLA", target_qty=5.0)
    repo.add(symbol="AAPL", target_qty=10.0)

    holdings = repo.list_all()

    assert [h["symbol"] for h in holdings] == ["AAPL", "TSLA"]


def test_remove_stops_tracking_the_symbol(config):
    repo = ManualHoldingRepository(Database(config))
    repo.add(symbol="AAPL", target_qty=10.0)

    repo.remove("AAPL")

    assert repo.list_all() == []


def test_remove_unknown_symbol_is_a_noop(config):
    repo = ManualHoldingRepository(Database(config))
    repo.remove("NONEXISTENT")
    assert repo.list_all() == []
