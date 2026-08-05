"""AccountSnapshotRepository: rolling Alpaca account equity/cash history.

trading_worker records one snapshot per trading cycle; `equity_history()`
returns it most-recent-first, matching the shape
strategy_engine.bots.draco.run_draco expects for its portfolio circuit
breaker (config["equity_history"]).
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from device_core.db.models import AccountSnapshot
from device_core.db.session import Database


def _row_to_dict(row: AccountSnapshot) -> dict[str, Any]:
    return {column.name: getattr(row, column.name) for column in row.__table__.columns}


class AccountSnapshotRepository:
    def __init__(self, db: Database) -> None:
        self._db = db

    def record(self, *, equity: float, cash: float) -> int:
        with self._db.session() as session:
            row = AccountSnapshot(equity=equity, cash=cash)
            session.add(row)
            session.flush()
            return row.id

    def recent(self, *, limit: int = 400) -> list[dict[str, Any]]:
        """Most-recent-first, mirroring Monstra-Worker's original
        `ORDER BY d DESC` query against trading.bot_equity."""
        with self._db.session() as session:
            rows = (
                session.query(AccountSnapshot)
                .order_by(AccountSnapshot.ts.desc(), AccountSnapshot.id.desc())
                .limit(limit)
                .all()
            )
            return [_row_to_dict(row) for row in rows]

    def equity_history(self, *, limit: int = 400) -> list[float]:
        return [row["equity"] for row in self.recent(limit=limit)]

    def equity_history_as_of(self, ts: datetime, *, limit: int = 400) -> list[float]:
        """equity_history(), but only rows recorded at or before `ts` - the
        equity_history a replayed past cycle would actually have seen as
        its config["equity_history"] input, for offline cycle-replay
        auditing (trading_worker.audit)."""
        with self._db.session() as session:
            rows = (
                session.query(AccountSnapshot)
                .filter(AccountSnapshot.ts <= ts)
                .order_by(AccountSnapshot.ts.desc(), AccountSnapshot.id.desc())
                .limit(limit)
                .all()
            )
            return [row.equity for row in rows]
