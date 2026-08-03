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


def test_bot_type_is_stored_separately_from_bot_slug(config):
    """bot_type carries the engine family (force/aptet/draco); bot_slug is
    the per-instance identity - see trading_worker/loop.py's _run_one_bot."""
    db = Database(config)
    repo = StrategyConfigRepository(db)

    repo.upsert(bot_slug="vectura_draco", bot_type="draco", source="monstra.pro")

    row = repo.get("vectura_draco")
    assert row["bot_slug"] == "vectura_draco"
    assert row["bot_type"] == "draco"


def test_bot_type_defaults_to_none_for_locally_seeded_rows(config):
    db = Database(config)
    repo = StrategyConfigRepository(db)

    repo.upsert(bot_slug="force")

    assert repo.get("force")["bot_type"] is None


def test_equity_weight_round_trips(config):
    db = Database(config)
    repo = StrategyConfigRepository(db)

    repo.upsert(bot_slug="vectura_draco", bot_type="draco", equity_weight=2.5, source="monstra.pro")

    assert repo.get("vectura_draco")["equity_weight"] == 2.5


def test_equity_weight_defaults_to_none_when_unset(config):
    db = Database(config)
    repo = StrategyConfigRepository(db)

    repo.upsert(bot_slug="force")

    assert repo.get("force")["equity_weight"] is None


def test_list_by_source_filters_correctly(config):
    db = Database(config)
    repo = StrategyConfigRepository(db)

    repo.upsert(bot_slug="force", source="local")
    repo.upsert(bot_slug="vectura_draco", bot_type="draco", source="monstra.pro")
    repo.upsert(bot_slug="quantus_aptet", bot_type="aptet", source="monstra.pro")

    monstra_pro_slugs = {row["bot_slug"] for row in repo.list_by_source("monstra.pro")}
    assert monstra_pro_slugs == {"vectura_draco", "quantus_aptet"}
    assert {row["bot_slug"] for row in repo.list_by_source("local")} == {"force"}
