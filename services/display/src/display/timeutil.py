"""Shared UTC-normalization for datetimes read back from device_core.

SQLite has no native timezone storage, so SQLAlchemy hands back naive
datetimes from `DateTime(timezone=True)` columns even though the value
written (via `utcnow()` defaults) was always UTC. `.astimezone()` on a
naive datetime assumes *local system time*, not UTC - silently wrong on
any machine not already set to UTC. Every datetime read back from
device_core must be normalized through `as_utc()` before comparison.

Extracted out of snapshot.py (and re-exported there for backward
compatibility) because candles.py needs the same normalization, and
snapshot.py imports candles.build_candles - importing as_utc from
snapshot.py there would be a circular import.
"""

from __future__ import annotations

from datetime import datetime, timezone


def as_utc(ts: datetime) -> datetime:
    if ts.tzinfo is None:
        return ts.replace(tzinfo=timezone.utc)
    return ts.astimezone(timezone.utc)
