"""BotStateRepository: cross-run state for stateful bots (e.g. draco's open
positions/regime/circuit-breaker), keyed by bot_slug.

trading_worker reads this before calling a bot's run_<bot>(config, state)
and writes back whatever that call returns in its `state` key - callers
that never received a non-None state (alpha1, aptet) simply never call
save(), and get(slug) returning None is the "first run" signal.
"""

from __future__ import annotations

from typing import Any

from device_core.db.models import BotState
from device_core.db.session import Database


class BotStateRepository:
    def __init__(self, db: Database) -> None:
        self._db = db

    def get(self, bot_slug: str) -> dict[str, Any] | None:
        with self._db.session() as session:
            row = session.query(BotState).filter_by(bot_slug=bot_slug).first()
            return dict(row.state_json or {}) if row is not None else None

    def save(self, bot_slug: str, state: dict[str, Any]) -> None:
        """Idempotent per bot_slug: a second call overwrites the existing row."""
        with self._db.session() as session:
            row = session.query(BotState).filter_by(bot_slug=bot_slug).first()
            if row is None:
                row = BotState(bot_slug=bot_slug)
                session.add(row)
            row.state_json = state

    def clear(self, bot_slug: str) -> None:
        with self._db.session() as session:
            row = session.query(BotState).filter_by(bot_slug=bot_slug).first()
            if row is not None:
                session.delete(row)
