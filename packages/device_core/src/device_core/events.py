"""Local pub/sub between services, backed by the device_event table.

trading_worker publishes (trade_executed, awaiting_activation,
connectivity_changed, ...); display subscribes by polling poll_since()
with its last-seen id as a cursor. Deliberately DB-backed rather than a
socket/HTTP mechanism in V1 - see ARCHITECTURE.md section 9.
"""

from __future__ import annotations

from enum import StrEnum
from typing import Any

from device_core.db.database import Database
from device_core.db.models import DeviceEvent


class EventType(StrEnum):
    AWAITING_ACTIVATION = "awaiting_activation"
    DEVICE_ACTIVATED = "device_activated"
    TRADE_EXECUTED = "trade_executed"
    CONNECTIVITY_CHANGED = "connectivity_changed"
    UPDATE_AVAILABLE = "update_available"
    ERROR = "error"


class EventBus:
    """Publishes/polls device_event rows through a shared Database."""

    def __init__(self, db: Database) -> None:
        self._db = db

    def publish(self, event_type: EventType | str, payload: dict[str, Any] | None = None) -> int:
        type_value = event_type.value if isinstance(event_type, EventType) else str(event_type)
        with self._db.session() as session:
            row = DeviceEvent(type=type_value, payload_json=payload or {})
            session.add(row)
            session.flush()
            return row.id

    def poll_since(self, since_id: int = 0, *, limit: int = 100) -> list[dict[str, Any]]:
        """Return events with id > since_id, oldest first. Callers should track
        the highest id they've seen and pass it back in as their next cursor."""
        with self._db.session() as session:
            rows = (
                session.query(DeviceEvent)
                .filter(DeviceEvent.id > since_id)
                .order_by(DeviceEvent.id.asc())
                .limit(limit)
                .all()
            )
            return [
                {"id": row.id, "ts": row.ts, "type": row.type, "payload": row.payload_json}
                for row in rows
            ]

    def latest_id(self) -> int:
        with self._db.session() as session:
            row = session.query(DeviceEvent).order_by(DeviceEvent.id.desc()).first()
            return row.id if row is not None else 0
