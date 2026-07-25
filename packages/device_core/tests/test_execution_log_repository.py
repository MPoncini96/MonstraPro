from device_core.db.session import Database
from device_core.repositories.execution_log import ExecutionLogRepository


def test_record_and_recent_roundtrip(config):
    db = Database(config)
    repo = ExecutionLogRepository(db)

    repo.record(level="INFO", component="worker", message="started", context={"pid": 123})
    repo.record(level="ERROR", component="worker", message="boom", context=None)

    recent = repo.recent(limit=10)
    assert len(recent) == 2
    assert recent[0]["message"] == "boom"  # most recent first
    assert recent[1]["context_json"] == {"pid": 123}


def test_recent_respects_limit(config):
    db = Database(config)
    repo = ExecutionLogRepository(db)

    for i in range(5):
        repo.record(level="INFO", component="worker", message=f"msg-{i}")

    assert len(repo.recent(limit=2)) == 2
