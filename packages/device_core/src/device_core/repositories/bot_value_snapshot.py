"""BotValueSnapshotRepository: approximate per-bot dollar value over time.

See device_core.db.models.BotValueSnapshot's docstring for what "value"
means here (current_weights-sum x account equity at snapshot time, not a
true segregated per-bot sub-account).

    core.bot_values.record(bot_slug="force", value=2450.0)
    core.bot_values.history("force", limit=400)  # most-recent-first
"""

from __future__ import annotations

from typing import Any

from device_core.db.models import BotValueSnapshot
from device_core.db.session import Database


def _row_to_dict(row: BotValueSnapshot) -> dict[str, Any]:
    return {column.name: getattr(row, column.name) for column in row.__table__.columns}


class BotValueSnapshotRepository:
    def __init__(self, db: Database) -> None:
        self._db = db

    def record(self, *, bot_slug: str, value: float) -> int:
        with self._db.session() as session:
            row = BotValueSnapshot(bot_slug=bot_slug, value=value)
            session.add(row)
            session.flush()
            return row.id

    def history(self, bot_slug: str, *, limit: int = 400) -> list[dict[str, Any]]:
        with self._db.session() as session:
            rows = (
                session.query(BotValueSnapshot)
                .filter_by(bot_slug=bot_slug)
                .order_by(BotValueSnapshot.ts.desc(), BotValueSnapshot.id.desc())
                .limit(limit)
                .all()
            )
            return [_row_to_dict(row) for row in rows]
