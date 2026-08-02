"""Builds the idle screen's stock performance view: one of the top-3
moving currently-held symbols, ranked by Alpaca's own intraday P&L% (not a
locally-derived proxy), with a candlestick chart built from
PositionSnapshotRepository's current_price history the same way the
portfolio view builds one from account_snapshot equity.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from device_core.core import DeviceCore

from display.candles import Candle, build_candles

DEFAULT_TOP_MOVERS_LIMIT = 3


@dataclass(frozen=True)
class StockView:
    symbol: str
    unrealized_plpc: float | None
    candles: list[Candle] = field(default_factory=list)


def top_movers(core: DeviceCore, *, limit: int = DEFAULT_TOP_MOVERS_LIMIT) -> list[str]:
    """Currently-held symbols ranked by |unrealized_intraday_plpc|
    (today's move, up or down), most-moved first."""
    positions = core.positions.latest_by_symbol()
    ranked = sorted(positions.values(), key=lambda p: abs(p["unrealized_intraday_plpc"]), reverse=True)
    return [p["symbol"] for p in ranked[:limit]]


def build_stock_view(core: DeviceCore, symbol: str) -> StockView:
    position = core.positions.latest_by_symbol().get(symbol)
    history = core.positions.history(symbol)
    candles = build_candles(history, value_key="current_price")

    return StockView(
        symbol=symbol,
        unrealized_plpc=position["unrealized_plpc"] if position else None,
        candles=candles,
    )
