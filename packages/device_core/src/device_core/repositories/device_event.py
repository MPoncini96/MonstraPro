"""DeviceEventRepository: the SQLite-backed local event queue.

    core.events.publish(EventType.TRADE_EXECUTED, {"bot_slug": "alpha1"})
    for event in core.events.list_unconsumed(limit=100):
        ...
        core.events.mark_consumed(event["id"], consumer="display")

Events preserve publish order (returned oldest-first by id) and remain in
list_unconsumed() until a consumer explicitly acknowledges them - there is
no time-based expiry and no at-most-once delivery guarantee beyond what the
consumer itself enforces by calling mark_consumed().
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from device_core.db.models import DeviceEvent
from device_core.db.session import Database
from device_core.events import VALID_SEVERITIES, EventType


def _row_to_dict(row: DeviceEvent) -> dict[str, Any]:
    return {column.name: getattr(row, column.name) for column in row.__table__.columns}


class DeviceEventRepository:
    def __init__(self, db: Database) -> None:
        self._db = db

    def publish(
        self,
        event_type: EventType | str,
        payload: dict[str, Any] | None = None,
        *,
        severity: str = "info",
    ) -> int:
        if severity not in VALID_SEVERITIES:
            raise ValueError(f"severity must be one of {sorted(VALID_SEVERITIES)}, got {severity!r}")
        type_value = event_type.value if isinstance(event_type, EventType) else str(event_type)
        with self._db.session() as session:
            row = DeviceEvent(type=type_value, severity=severity, payload_json=payload or {})
            session.add(row)
            session.flush()
            return row.id

    def list_unconsumed(self, limit: int = 100) -> list[dict[str, Any]]:
        with self._db.session() as session:
            rows = (
                session.query(DeviceEvent)
                .filter(DeviceEvent.consumed_at.is_(None))
                .order_by(DeviceEvent.id.asc())
                .limit(limit)
                .all()
            )
            return [_row_to_dict(row) for row in rows]

    def mark_consumed(self, event_id: int, consumer: str) -> None:
        with self._db.session() as session:
            row = session.get(DeviceEvent, event_id)
            if row is None:
                raise ValueError(f"No device_event with id {event_id}")
            row.consumed_at = datetime.now(timezone.utc)
            row.consumed_by = consumer
