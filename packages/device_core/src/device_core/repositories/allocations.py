"""PortfolioAllocationRepository: historical target vs. current weights.

`replace()` validates both weight dicts *inside* the transaction, so an
invalid call genuinely rolls back (via Database.session()'s except branch)
rather than being rejected by a pre-transaction guard - nothing is written
and the previous latest() reading is left untouched.
"""

from __future__ import annotations

from typing import Any

from device_core.db.models import PortfolioAllocation
from device_core.db.session import Database

_WEIGHT_SUM_TOLERANCE = 0.01


class InvalidAllocationError(ValueError):
    """Raised when a weights dict doesn't sum to ~1.0."""


def _row_to_dict(row: PortfolioAllocation) -> dict[str, Any]:
    return {column.name: getattr(row, column.name) for column in row.__table__.columns}


def _validate_weights(weights: dict[str, Any]) -> None:
    if not weights:
        return
    total = sum(weights.values())
    if abs(total - 1.0) > _WEIGHT_SUM_TOLERANCE:
        raise InvalidAllocationError(f"weights must sum to ~1.0, got {total}")


class PortfolioAllocationRepository:
    def __init__(self, db: Database) -> None:
        self._db = db

    def replace(
        self, *, bot_slug: str, target_weights: dict[str, Any], current_weights: dict[str, Any]
    ) -> dict[str, Any]:
        with self._db.session() as session:
            _validate_weights(target_weights)
            _validate_weights(current_weights)
            row = PortfolioAllocation(
                bot_slug=bot_slug,
                target_weights_json=target_weights,
                current_weights_json=current_weights,
            )
            session.add(row)
            session.flush()
            return _row_to_dict(row)

    def latest(self, bot_slug: str) -> dict[str, Any] | None:
        with self._db.session() as session:
            row = (
                session.query(PortfolioAllocation)
                .filter_by(bot_slug=bot_slug)
                .order_by(PortfolioAllocation.ts.desc(), PortfolioAllocation.id.desc())
                .first()
            )
            return _row_to_dict(row) if row is not None else None

    def history(self, bot_slug: str, *, limit: int = 100) -> list[dict[str, Any]]:
        with self._db.session() as session:
            rows = (
                session.query(PortfolioAllocation)
                .filter_by(bot_slug=bot_slug)
                .order_by(PortfolioAllocation.ts.desc(), PortfolioAllocation.id.desc())
                .limit(limit)
                .all()
            )
            return [_row_to_dict(row) for row in rows]
