"""ManualHoldingRepository: individually-held, locked-quantity stocks the
owner added directly (services/portfolio_web), outside of any bot's
algorithm. See device_core.db.models.ManualHolding's docstring for what
"locked" means and which code is allowed to trade these symbols.

    core.manual_holdings.add(symbol="AAPL", target_qty=10)
    core.manual_holdings.list_all()             # all locked symbols
    core.manual_holdings.remove("AAPL")          # stop protecting, doesn't sell
"""

from __future__ import annotations

from typing import Any

from device_core.db.models import ManualHolding
from device_core.db.session import Database


def _row_to_dict(row: ManualHolding) -> dict[str, Any]:
    return {column.name: getattr(row, column.name) for column in row.__table__.columns}


class ManualHoldingRepository:
    def __init__(self, db: Database) -> None:
        self._db = db

    def add(self, *, symbol: str, target_qty: float) -> dict[str, Any]:
        """Idempotent per symbol: a second call updates the existing row's
        target_qty rather than creating a duplicate - lets an owner raise
        or lower a locked position's target without a separate "edit" verb."""
        if target_qty <= 0:
            raise ValueError(f"target_qty must be positive, got {target_qty}")
        with self._db.session() as session:
            row = session.query(ManualHolding).filter_by(symbol=symbol).first()
            if row is None:
                row = ManualHolding(symbol=symbol, target_qty=target_qty)
                session.add(row)
            else:
                row.target_qty = target_qty
            session.flush()
            return _row_to_dict(row)

    def list_all(self) -> list[dict[str, Any]]:
        with self._db.session() as session:
            rows = session.query(ManualHolding).order_by(ManualHolding.symbol.asc()).all()
            return [_row_to_dict(row) for row in rows]

    def remove(self, symbol: str) -> None:
        """Stops protecting `symbol` from bot rebalancing going forward.
        Never sells the underlying shares - see this module's docstring."""
        with self._db.session() as session:
            session.query(ManualHolding).filter_by(symbol=symbol).delete()
