from datetime import datetime, timedelta, timezone

import pytest

from device_core.db.models import PortfolioAllocation
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


def test_as_of_returns_the_row_in_effect_at_a_past_cycle(config):
    """For trading_worker.audit's execution-fidelity replay: as_of() must
    return whatever was the LATEST allocation at or before the given
    timestamp, not simply the newest row overall."""
    db = Database(config)
    repo = PortfolioAllocationRepository(db)

    old = repo.replace(bot_slug="alpha1", target_weights={"AAPL": 1.0}, current_weights={})
    with db.session() as session:
        row = session.query(PortfolioAllocation).filter_by(id=old["id"]).one()
        row.ts = datetime.now(timezone.utc) - timedelta(hours=1)

    repo.replace(bot_slug="alpha1", target_weights={"MSFT": 1.0}, current_weights={})

    as_of_between = repo.as_of("alpha1", datetime.now(timezone.utc) - timedelta(minutes=30))
    assert as_of_between["target_weights_json"] == {"AAPL": 1.0}

    as_of_now = repo.as_of("alpha1", datetime.now(timezone.utc))
    assert as_of_now["target_weights_json"] == {"MSFT": 1.0}


def test_as_of_returns_none_when_no_row_existed_yet(config):
    db = Database(config)
    repo = PortfolioAllocationRepository(db)

    repo.replace(bot_slug="alpha1", target_weights={"AAPL": 1.0}, current_weights={})

    assert repo.as_of("alpha1", datetime.now(timezone.utc) - timedelta(days=1)) is None
