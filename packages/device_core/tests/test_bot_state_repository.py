from device_core.db.session import Database
from device_core.repositories.bot_state import BotStateRepository


def test_get_returns_none_for_unknown_slug(config):
    db = Database(config)
    repo = BotStateRepository(db)

    assert repo.get("draco") is None


def test_save_and_get_round_trip(config):
    db = Database(config)
    repo = BotStateRepository(db)

    state = {"positions": {"AAPL": {"entry_price": 150.0}}, "cooldowns": {}}
    repo.save("draco", state)

    assert repo.get("draco") == state


def test_save_is_idempotent_per_slug(config):
    db = Database(config)
    repo = BotStateRepository(db)

    repo.save("draco", {"positions": {}})
    repo.save("draco", {"positions": {"AAPL": {}}})

    assert repo.get("draco") == {"positions": {"AAPL": {}}}


def test_clear_removes_state(config):
    db = Database(config)
    repo = BotStateRepository(db)

    repo.save("draco", {"positions": {}})
    repo.clear("draco")

    assert repo.get("draco") is None
