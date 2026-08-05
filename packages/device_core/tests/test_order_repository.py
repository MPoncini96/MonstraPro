import pytest

from device_core.db.session import Database
from device_core.repositories.orders import OrderRepository


def test_record_requires_qty_or_notional(config):
    db = Database(config)
    repo = OrderRepository(db)

    with pytest.raises(ValueError):
        repo.record(bot_slug="force", symbol="AAPL", side="buy", status="submitted")


def test_record_rejects_invalid_side(config):
    db = Database(config)
    repo = OrderRepository(db)

    with pytest.raises(ValueError):
        repo.record(bot_slug="force", symbol="AAPL", side="short", qty=1.0, status="submitted")


def test_record_and_recent_round_trip(config):
    db = Database(config)
    repo = OrderRepository(db)

    repo.record(bot_slug="force", symbol="AAPL", side="buy", qty=3.5, status="submitted")
    repo.record(bot_slug="force", symbol="MSFT", side="sell", notional=100.0, status="submitted")
    repo.record(bot_slug="draco", symbol="NVDA", side="buy", qty=1.0, status="submitted")

    force_orders = repo.recent(bot_slug="force")
    assert [o["symbol"] for o in force_orders] == ["MSFT", "AAPL"]  # newest first

    all_orders = repo.recent()
    assert len(all_orders) == 3


def test_mark_filled_updates_status_and_timestamp(config):
    from datetime import datetime, timezone

    db = Database(config)
    repo = OrderRepository(db)

    order_id = repo.record(bot_slug="force", symbol="AAPL", side="buy", qty=1.0, status="submitted")
    filled_at = datetime.now(timezone.utc)
    repo.mark_filled(order_id, filled_at=filled_at, raw_response={"status": "filled"})

    [order] = repo.recent(bot_slug="force")
    assert order["status"] == "filled"
    assert order["filled_at"] is not None
    assert order["raw_response_json"] == {"status": "filled"}


def test_mark_filled_unknown_id_raises(config):
    db = Database(config)
    repo = OrderRepository(db)

    from datetime import datetime, timezone

    with pytest.raises(ValueError):
        repo.mark_filled(999, filled_at=datetime.now(timezone.utc))


def test_in_window_filters_by_submitted_at_range(config):
    """For trading_worker.audit's execution-fidelity replay: orders are
    correlated to a cycle by proximity to that cycle's timestamp, not a
    direct foreign key (Order has none - see loop.py's module docstring)."""
    from datetime import datetime, timedelta, timezone

    db = Database(config)
    repo = OrderRepository(db)
    now = datetime.now(timezone.utc)

    repo.record(bot_slug="_portfolio", symbol="AAPL", side="buy", notional=100.0, status="accepted", submitted_at=now - timedelta(hours=2))
    repo.record(bot_slug="_portfolio", symbol="MSFT", side="sell", notional=50.0, status="accepted", submitted_at=now)
    repo.record(bot_slug="force", symbol="NVDA", side="buy", notional=25.0, status="accepted", submitted_at=now)

    windowed = repo.in_window(start=now - timedelta(seconds=90), end=now + timedelta(seconds=90))
    symbols = {order["symbol"] for order in windowed}
    assert symbols == {"MSFT", "NVDA"}  # AAPL is outside the window

    scoped = repo.in_window(start=now - timedelta(seconds=90), end=now + timedelta(seconds=90), bot_slug="_portfolio")
    assert [order["symbol"] for order in scoped] == ["MSFT"]
