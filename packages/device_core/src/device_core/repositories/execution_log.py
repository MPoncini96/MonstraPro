"""ExecutionLogRepository: persisted structured application log.

Written to directly by callers, and by device_core.logging.attach_db_handler
on behalf of the standard logging module - see logging.py for redaction,
which happens before context ever reaches here.
"""

from __future__ import annotations

from typing import Any

from device_core.db.models import ExecutionLog
from device_core.db.session import Database


def _row_to_dict(row: ExecutionLog) -> dict[str, Any]:
    return {column.name: getattr(row, column.name) for column in row.__table__.columns}


class ExecutionLogRepository:
    def __init__(self, db: Database) -> None:
        self._db = db

    def record(
        self, *, level: str, component: str, message: str, context: dict[str, Any] | None = None
    ) -> int:
        with self._db.session() as session:
            row = ExecutionLog(level=level, component=component, message=message, context_json=context or {})
            session.add(row)
            session.flush()
            return row.id

    def recent(self, limit: int = 100) -> list[dict[str, Any]]:
        with self._db.session() as session:
            rows = session.query(ExecutionLog).order_by(ExecutionLog.id.desc()).limit(limit).all()
            return [_row_to_dict(row) for row in rows]
