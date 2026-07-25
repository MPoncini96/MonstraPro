from device_core.db.session import Database
from device_core.repositories.strategy_config import StrategyConfigRepository


def test_upsert_is_idempotent_per_bot_slug(config):
    db = Database(config)
    repo = StrategyConfigRepository(db)

    repo.upsert(bot_slug="alpha1", target_allocation={"AAPL": 1.0})
    repo.upsert(bot_slug="alpha1", display_name="Force", target_allocation={"AAPL": 0.5, "MSFT": 0.5})

    active = repo.get_active()
    assert len(active) == 1
    assert active[0]["display_name"] == "Force"
    assert active[0]["target_allocation_json"] == {"AAPL": 0.5, "MSFT": 0.5}


def test_get_active_excludes_inactive(config):
    db = Database(config)
    repo = StrategyConfigRepository(db)

    repo.upsert(bot_slug="alpha1", is_active=True)
    repo.upsert(bot_slug="alpha2", is_active=False)

    active_slugs = {row["bot_slug"] for row in repo.get_active()}
    assert active_slugs == {"alpha1"}


def test_get_returns_none_for_unknown_slug(config):
    db = Database(config)
    repo = StrategyConfigRepository(db)
    assert repo.get("nonexistent") is None
