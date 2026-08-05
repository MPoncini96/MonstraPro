from datetime import datetime, timedelta, timezone

from device_core.db.models import PositionSnapshot
from device_core.db.session import Database
from device_core.repositories.position_snapshot import PositionSnapshotRepository


def _record(repo, **overrides):
    defaults = dict(
        symbol="AAPL",
        qty=10.0,
        avg_entry_price=150.0,
        current_price=155.0,
        market_value=1550.0,
        unrealized_pl=50.0,
        unrealized_plpc=0.0333,
        unrealized_intraday_plpc=0.012,
    )
    defaults.update(overrides)
    return repo.record(**defaults)


def test_record_returns_row_id(config):
    repo = PositionSnapshotRepository(Database(config))
    row_id = _record(repo)
    assert isinstance(row_id, int)


def test_latest_by_symbol_returns_most_recent_row_per_symbol(config):
    repo = PositionSnapshotRepository(Database(config))
    _record(repo, symbol="AAPL", current_price=150.0)
    _record(repo, symbol="AAPL", current_price=160.0)
    _record(repo, symbol="MSFT", current_price=300.0)

    latest = repo.latest_by_symbol()

    assert set(latest.keys()) == {"AAPL", "MSFT"}
    assert latest["AAPL"]["current_price"] == 160.0


def test_latest_by_symbol_excludes_rows_outside_the_recency_window(config):
    db = Database(config)
    repo = PositionSnapshotRepository(db)
    _record(repo, symbol="OLD")

    # Backdate the row directly - simulates a position that was closed long
    # ago and never got a fresh snapshot since.
    with db.session() as session:
        row = session.query(PositionSnapshot).filter_by(symbol="OLD").one()
        row.ts = datetime.now(timezone.utc) - timedelta(hours=1)

    latest = repo.latest_by_symbol(within_seconds=300)

    assert "OLD" not in latest


def test_history_is_most_recent_first_and_scoped_to_symbol(config):
    repo = PositionSnapshotRepository(Database(config))
    _record(repo, symbol="AAPL", current_price=150.0)
    _record(repo, symbol="MSFT", current_price=300.0)
    _record(repo, symbol="AAPL", current_price=152.0)

    history = repo.history("AAPL")

    assert [row["current_price"] for row in history] == [152.0, 150.0]


def test_history_respects_limit(config):
    repo = PositionSnapshotRepository(Database(config))
    for i in range(5):
        _record(repo, symbol="AAPL", current_price=100.0 + i)

    history = repo.history("AAPL", limit=2)

    assert len(history) == 2


def test_as_of_returns_most_recent_row_per_symbol_at_or_before_ts(config):
    """For trading_worker.audit's execution-fidelity replay: as_of() must
    reconstruct what positions looked like at a past cycle, not "currently
    held" (unlike latest_by_symbol(), it has no recency window)."""
    db = Database(config)
    repo = PositionSnapshotRepository(db)

    old_id = _record(repo, symbol="AAPL", current_price=150.0)
    with db.session() as session:
        row = session.query(PositionSnapshot).filter_by(id=old_id).one()
        row.ts = datetime.now(timezone.utc) - timedelta(hours=1)

    _record(repo, symbol="AAPL", current_price=160.0)
    _record(repo, symbol="MSFT", current_price=300.0)

    as_of_between = repo.as_of(datetime.now(timezone.utc) - timedelta(minutes=30))
    assert as_of_between["AAPL"]["current_price"] == 150.0
    assert "MSFT" not in as_of_between  # MSFT's only row is after this ts

    as_of_now = repo.as_of(datetime.now(timezone.utc))
    assert as_of_now["AAPL"]["current_price"] == 160.0
    assert as_of_now["MSFT"]["current_price"] == 300.0
