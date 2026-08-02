"""OrderRepository: every order trading_worker submits to Alpaca."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from device_core.db.models import Order
from device_core.db.session import Database

_VALID_SIDES = frozenset({"buy", "sell"})


def _row_to_dict(row: Order) -> dict[str, Any]:
    return {column.name: getattr(row, column.name) for column in row.__table__.columns}


class OrderRepository:
    def __init__(self, db: Database) -> None:
        self._db = db

    def record(
        self,
        *,
        bot_slug: str,
        symbol: str,
        side: str,
        qty: float | None = None,
        notional: float | None = None,
        order_type: str = "market",
        status: str,
        alpaca_order_id: str | None = None,
        raw_response: dict[str, Any] | None = None,
        submitted_at: datetime | None = None,
    ) -> int:
        if side not in _VALID_SIDES:
            raise ValueError(f"side must be one of {sorted(_VALID_SIDES)}, got {side!r}")
        if qty is None and notional is None:
            raise ValueError("one of qty or notional must be set")

        with self._db.session() as session:
            row = Order(
                bot_slug=bot_slug,
                symbol=symbol,
                side=side,
                qty=qty,
                notional=notional,
                order_type=order_type,
                status=status,
                alpaca_order_id=alpaca_order_id,
                raw_response_json=raw_response or {},
            )
            if submitted_at is not None:
                row.submitted_at = submitted_at
            session.add(row)
            session.flush()
            return row.id

    def mark_filled(self, order_id: int, *, filled_at: datetime, raw_response: dict[str, Any] | None = None) -> None:
        with self._db.session() as session:
            row = session.get(Order, order_id)
            if row is None:
                raise ValueError(f"No order with id {order_id}")
            row.status = "filled"
            row.filled_at = filled_at
            if raw_response is not None:
                row.raw_response_json = raw_response

    def recent(self, bot_slug: str | None = None, *, limit: int = 100) -> list[dict[str, Any]]:
        with self._db.session() as session:
            query = session.query(Order)
            if bot_slug is not None:
                query = query.filter_by(bot_slug=bot_slug)
            rows = query.order_by(Order.id.desc()).limit(limit).all()
            return [_row_to_dict(row) for row in rows]
