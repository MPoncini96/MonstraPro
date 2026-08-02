from device_core.db.session import Database
from device_core.repositories.bot_value_snapshot import BotValueSnapshotRepository


def test_record_returns_row_id(config):
    repo = BotValueSnapshotRepository(Database(config))
    row_id = repo.record(bot_slug="force", value=2450.0)
    assert isinstance(row_id, int)


def test_history_is_most_recent_first_and_scoped_to_bot_slug(config):
    repo = BotValueSnapshotRepository(Database(config))
    repo.record(bot_slug="force", value=1000.0)
    repo.record(bot_slug="aptet", value=500.0)
    repo.record(bot_slug="force", value=1050.0)

    history = repo.history("force")

    assert [row["value"] for row in history] == [1050.0, 1000.0]


def test_history_respects_limit(config):
    repo = BotValueSnapshotRepository(Database(config))
    for i in range(5):
        repo.record(bot_slug="force", value=1000.0 + i)

    history = repo.history("force", limit=2)

    assert len(history) == 2


def test_history_empty_for_unknown_bot(config):
    repo = BotValueSnapshotRepository(Database(config))
    assert repo.history("nonexistent") == []
