import pytest

from device_core.db.session import Database
from device_core.repositories.allocations import InvalidAllocationError, PortfolioAllocationRepository


def test_replace_succeeds_with_valid_weights(config):
    db = Database(config)
    repo = PortfolioAllocationRepository(db)

    row = repo.replace(bot_slug="alpha1", target_weights={"AAPL": 0.6, "MSFT": 0.4}, current_weights={"AAPL": 1.0})

    assert row["target_weights_json"] == {"AAPL": 0.6, "MSFT": 0.4}
    assert repo.latest("alpha1")["id"] == row["id"]


def test_replace_rolls_back_on_invalid_weights(config):
    db = Database(config)
    repo = PortfolioAllocationRepository(db)

    valid = repo.replace(bot_slug="alpha1", target_weights={"AAPL": 1.0}, current_weights={"AAPL": 1.0})

    with pytest.raises(InvalidAllocationError):
        repo.replace(bot_slug="alpha1", target_weights={"AAPL": 0.3}, current_weights={"AAPL": 1.0})

    still_latest = repo.latest("alpha1")
    assert still_latest["id"] == valid["id"]
    assert still_latest["target_weights_json"] == {"AAPL": 1.0}

    with db.session() as session:
        from device_core.db.models import PortfolioAllocation

        assert session.query(PortfolioAllocation).filter_by(bot_slug="alpha1").count() == 1


def test_latest_returns_none_when_no_history(config):
    db = Database(config)
    repo = PortfolioAllocationRepository(db)
    assert repo.latest("never-seen") is None


def test_history_orders_newest_first(config):
    db = Database(config)
    repo = PortfolioAllocationRepository(db)

    repo.replace(bot_slug="alpha1", target_weights={"AAPL": 1.0}, current_weights={"AAPL": 1.0})
    repo.replace(bot_slug="alpha1", target_weights={"MSFT": 1.0}, current_weights={"AAPL": 1.0})

    history = repo.history("alpha1")
    assert [row["target_weights_json"] for row in history] == [{"MSFT": 1.0}, {"AAPL": 1.0}]
