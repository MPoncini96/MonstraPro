"""StrategyConfigRepository: the owner's configured strategy/strategies."""

from __future__ import annotations

from typing import Any

from device_core.db.models import StrategyConfig
from device_core.db.session import Database


def _row_to_dict(row: StrategyConfig) -> dict[str, Any]:
    return {column.name: getattr(row, column.name) for column in row.__table__.columns}


class StrategyConfigRepository:
    def __init__(self, db: Database) -> None:
        self._db = db

    def upsert(
        self,
        *,
        bot_slug: str,
        bot_type: str | None = None,
        display_name: str | None = None,
        params: dict[str, Any] | None = None,
        target_allocation: dict[str, Any] | None = None,
        is_active: bool = True,
        source: str = "local",
    ) -> dict[str, Any]:
        """Idempotent per bot_slug: a second call updates the existing row
        rather than creating a duplicate. Every field (including bot_type)
        is fully replaced by each call, not merged - same "whole row"
        semantics this already had before bot_type existed."""
        with self._db.session() as session:
            row = session.query(StrategyConfig).filter_by(bot_slug=bot_slug).first()
            if row is None:
                row = StrategyConfig(bot_slug=bot_slug)
                session.add(row)
            row.bot_type = bot_type
            row.display_name = display_name
            row.params_json = params or {}
            row.target_allocation_json = target_allocation or {}
            row.is_active = is_active
            row.source = source
            session.flush()
            return _row_to_dict(row)

    def get(self, bot_slug: str) -> dict[str, Any] | None:
        with self._db.session() as session:
            row = session.query(StrategyConfig).filter_by(bot_slug=bot_slug).first()
            return _row_to_dict(row) if row is not None else None

    def get_active(self) -> list[dict[str, Any]]:
        with self._db.session() as session:
            rows = session.query(StrategyConfig).filter_by(is_active=True).all()
            return [_row_to_dict(row) for row in rows]

    def list_by_source(self, source: str) -> list[dict[str, Any]]:
        with self._db.session() as session:
            rows = session.query(StrategyConfig).filter_by(source=source).all()
            return [_row_to_dict(row) for row in rows]
