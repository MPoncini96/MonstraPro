"""SignalRepository: signal history per bot, with duplicate-signal prevention.

Mirrors Monstra-Worker's fingerprint_signal/should_write_signal pattern
(worker.py): a signal identical to the most recent one for the same
(bot_id, bot_type) - same signal value, note, and payload - is not
rewritten. store() reports whether it actually wrote a new row so callers
can decide whether to react (e.g. publish a device_event) only on change.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, NamedTuple

from device_core.db.models import Signal
from device_core.db.session import Database


class SignalWriteResult(NamedTuple):
    id: int
    written: bool


def _row_to_dict(row: Signal) -> dict[str, Any]:
    return {column.name: getattr(row, column.name) for column in row.__table__.columns}


class SignalRepository:
    def __init__(self, db: Database) -> None:
        self._db = db

    def store(
        self,
        *,
        bot_id: str,
        bot_type: str,
        signal: str,
        note: str | None = None,
        payload: dict[str, Any] | None = None,
        ts: datetime | None = None,
    ) -> SignalWriteResult:
        normalized_payload = payload or {}
        with self._db.session() as session:
            last = (
                session.query(Signal)
                .filter_by(bot_id=bot_id, bot_type=bot_type)
                .order_by(Signal.ts.desc(), Signal.id.desc())
                .first()
            )
            if (
                last is not None
                and last.signal == signal
                and (last.note or None) == note
                and (last.payload_json or {}) == normalized_payload
            ):
                return SignalWriteResult(id=last.id, written=False)

            row = Signal(bot_id=bot_id, bot_type=bot_type, signal=signal, note=note, payload_json=normalized_payload)
            if ts is not None:
                row.ts = ts
            session.add(row)
            session.flush()
            return SignalWriteResult(id=row.id, written=True)

    def latest(self, bot_id: str, bot_type: str) -> dict[str, Any] | None:
        with self._db.session() as session:
            row = (
                session.query(Signal)
                .filter_by(bot_id=bot_id, bot_type=bot_type)
                .order_by(Signal.ts.desc(), Signal.id.desc())
                .first()
            )
            return _row_to_dict(row) if row is not None else None

    def count_for(self, bot_id: str, bot_type: str) -> int:
        with self._db.session() as session:
            return session.query(Signal).filter_by(bot_id=bot_id, bot_type=bot_type).count()
