from device_core.db.session import Database
from device_core.repositories.account_snapshot import AccountSnapshotRepository


def test_recent_returns_most_recent_first(config):
    db = Database(config)
    repo = AccountSnapshotRepository(db)

    repo.record(equity=100.0, cash=10.0)
    repo.record(equity=110.0, cash=5.0)
    repo.record(equity=105.0, cash=8.0)

    recent = repo.recent()
    assert [row["equity"] for row in recent] == [105.0, 110.0, 100.0]


def test_equity_history_matches_recent_equities(config):
    db = Database(config)
    repo = AccountSnapshotRepository(db)

    repo.record(equity=100.0, cash=10.0)
    repo.record(equity=90.0, cash=20.0)

    assert repo.equity_history() == [90.0, 100.0]


def test_recent_respects_limit(config):
    db = Database(config)
    repo = AccountSnapshotRepository(db)

    for i in range(5):
        repo.record(equity=float(i), cash=0.0)

    assert len(repo.recent(limit=2)) == 2
