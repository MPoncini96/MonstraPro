"""Builds the idle screen's "last trade" line: the most recently submitted
order, plus - if the resulting position is still held - its unrealized
gain/loss straight from Alpaca's own position data (device_core's
position_snapshot table), not a locally-derived proxy.

This deliberately does NOT attempt the per-trade *realized* win/loss
Objectives.txt originally asked for and that services/display/src/display
/snapshot.py's module docstring already explains was tried and discarded
(a naive proportional-notional approximation is mathematically incapable
of ever reporting a loss). This is *unrealized* P&L on a position that may
still be open, computed by Alpaca from real fill data - a different,
honest metric, not a re-attempt at the discarded one.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from device_core.core import DeviceCore


@dataclass(frozen=True)
class LastTradeInfo:
    symbol: str
    side: str
    notional: float | None
    status: str
    unrealized_pl: float | None
    unrealized_plpc: float | None


def build_last_trade(core: DeviceCore) -> LastTradeInfo | None:
    orders = core.orders.recent(limit=1)
    if not orders:
        return None
    order: dict[str, Any] = orders[0]

    position = core.positions.latest_by_symbol().get(order["symbol"])

    return LastTradeInfo(
        symbol=order["symbol"],
        side=order["side"],
        notional=order.get("notional"),
        status=order["status"],
        unrealized_pl=position["unrealized_pl"] if position else None,
        unrealized_plpc=position["unrealized_plpc"] if position else None,
    )
