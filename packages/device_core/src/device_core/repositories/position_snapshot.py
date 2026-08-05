"""PositionSnapshotRepository: rolling local cache of held Alpaca positions.

    core.positions.record(symbol="AAPL", qty=10, avg_entry_price=150.0,
                           current_price=155.0, market_value=1550.0,
                           unrealized_pl=50.0, unrealized_plpc=0.033,
                           unrealized_intraday_plpc=0.012)
    core.positions.latest_by_symbol()          # {"AAPL": {...}, ...}
    core.positions.history("AAPL", limit=400)  # most-recent-first
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any

from device_core.db.models import PositionSnapshot
from device_core.db.session import Database

DEFAULT_CURRENTLY_HELD_WINDOW_SECONDS = 300


def _row_to_dict(row: PositionSnapshot) -> dict[str, Any]:
    return {column.name: getattr(row, column.name) for column in row.__table__.columns}


class PositionSnapshotRepository:
    def __init__(self, db: Database) -> None:
        self._db = db

    def record(
        self,
        *,
        symbol: str,
        qty: float,
        avg_entry_price: float,
        current_price: float,
        market_value: float,
        unrealized_pl: float,
        unrealized_plpc: float,
        unrealized_intraday_plpc: float,
    ) -> int:
        with self._db.session() as session:
            row = PositionSnapshot(
                symbol=symbol,
                qty=qty,
                avg_entry_price=avg_entry_price,
                current_price=current_price,
                market_value=market_value,
                unrealized_pl=unrealized_pl,
                unrealized_plpc=unrealized_plpc,
                unrealized_intraday_plpc=unrealized_intraday_plpc,
            )
            session.add(row)
            session.flush()
            return row.id

    def latest_by_symbol(self, *, within_seconds: int = DEFAULT_CURRENTLY_HELD_WINDOW_SECONDS) -> dict[str, dict[str, Any]]:
        """Most recent row per symbol, considering only rows recorded in the
        last `within_seconds`. A closed position simply stops getting new
        rows once trading_worker's own list_positions() no longer includes
        it - bounding the window here is what makes it drop out of
        "currently held" (and thus out of top_movers/last-trade lookups)
        instead of its last-known row lingering forever."""
        cutoff = datetime.now(timezone.utc) - timedelta(seconds=within_seconds)
        with self._db.session() as session:
            rows = (
                session.query(PositionSnapshot)
                .filter(PositionSnapshot.ts >= cutoff)
                .order_by(PositionSnapshot.ts.desc(), PositionSnapshot.id.desc())
                .all()
            )
            result: dict[str, dict[str, Any]] = {}
            for row in rows:
                data = _row_to_dict(row)
                result.setdefault(data["symbol"], data)  # first hit per symbol is the newest (desc order)
            return result

    def as_of(self, ts: datetime) -> dict[str, dict[str, Any]]:
        """Most recent row per symbol at or before `ts` - the historical
        counterpart to latest_by_symbol() (which is always relative to
        "now"), used to reconstruct what positions looked like during a
        past trading cycle for offline cycle-replay auditing
        (trading_worker.audit). Unlike latest_by_symbol(), this has no
        recency window - a symbol closed long before `ts` still isn't
        "current" as of `ts`, but the caller decides that from `qty`/
        `market_value`, not by this method silently dropping the row."""
        with self._db.session() as session:
            rows = (
                session.query(PositionSnapshot)
                .filter(PositionSnapshot.ts <= ts)
                .order_by(PositionSnapshot.ts.desc(), PositionSnapshot.id.desc())
                .all()
            )
            result: dict[str, dict[str, Any]] = {}
            for row in rows:
                data = _row_to_dict(row)
                result.setdefault(data["symbol"], data)  # first hit per symbol is the newest (desc order)
            return result

    def history(self, symbol: str, *, limit: int = 400) -> list[dict[str, Any]]:
        """Most-recent-first, matching AccountSnapshotRepository.recent()'s
        shape/ordering convention."""
        with self._db.session() as session:
            rows = (
                session.query(PositionSnapshot)
                .filter_by(symbol=symbol)
                .order_by(PositionSnapshot.ts.desc(), PositionSnapshot.id.desc())
                .limit(limit)
                .all()
            )
            return [_row_to_dict(row) for row in rows]
