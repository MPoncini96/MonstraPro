"""Selects which stocks display's per-stock idle screen should show, and
keeps their chart data (device_core.MarketDataCache) fresh from Alpaca's
market-data API.

Owner-specified selection (not a generic "top movers" ranking): the 3
currently-held symbols with the largest position (by market value), plus
the 2 with the biggest move over the last trading day (by
|unrealized_intraday_plpc|), deduplicated so a symbol that qualifies both
ways only shows once and the 5th slot goes to the next-biggest mover
instead.

Each selected symbol gets three independently-fetched "slides" - see
SLIDE_SPECS below for exactly what window/granularity each one is. This
runs on its own slower cadence (STOCK_BAR_SYNC_INTERVAL_SECONDS in main.py),
not every trading-cycle tick - 5 symbols x 3 slides is 15 Alpaca market-data
calls per sync, and none of these charts need up-to-the-minute freshness the
way trading signals do.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any

from alpaca.data.timeframe import TimeFrame, TimeFrameUnit

from trading_worker.alpaca_client import AlpacaClient

logger = logging.getLogger(__name__)

TOP_POSITION_COUNT = 3
TOP_MOVEMENT_COUNT = 2


@dataclass(frozen=True)
class SlideSpec:
    lookback: timedelta
    timeframe: TimeFrame


# "1h"/"1d"/"1y" match device_core.MarketDataCache.slide and
# display/stock_view.py's three-slide rotation.
SLIDE_SPECS: dict[str, SlideSpec] = {
    "1h": SlideSpec(lookback=timedelta(hours=1), timeframe=TimeFrame(1, TimeFrameUnit.Minute)),
    "1d": SlideSpec(lookback=timedelta(days=1), timeframe=TimeFrame(15, TimeFrameUnit.Minute)),
    "1y": SlideSpec(lookback=timedelta(days=365), timeframe=TimeFrame.Day),
}


def select_symbols_to_track(
    alpaca: AlpacaClient,
    *,
    top_position_count: int = TOP_POSITION_COUNT,
    top_movement_count: int = TOP_MOVEMENT_COUNT,
) -> list[str]:
    positions = alpaca.list_positions()

    by_position_size = sorted(positions, key=lambda p: p.market_value, reverse=True)
    top_by_position = [p.symbol for p in by_position_size[:top_position_count]]

    already_selected = set(top_by_position)
    by_movement = sorted(
        (p for p in positions if p.symbol not in already_selected),
        key=lambda p: abs(p.unrealized_intraday_plpc),
        reverse=True,
    )
    top_by_movement = [p.symbol for p in by_movement[:top_movement_count]]

    return top_by_position + top_by_movement


def _bars_to_json(bars: list[Any]) -> list[dict[str, Any]]:
    return [
        {"ts": bar.ts.isoformat(), "open": bar.open, "high": bar.high, "low": bar.low, "close": bar.close}
        for bar in bars
    ]


def sync_stock_bars(core: Any, alpaca: AlpacaClient, *, now: datetime | None = None) -> list[str]:
    """Selects symbols, refreshes their cached bars, and prunes anything no
    longer selected. Returns the selected symbols (mainly for logging/tests -
    display reads the cache itself, not this return value)."""
    now = now or datetime.now(timezone.utc)
    symbols = select_symbols_to_track(alpaca)

    for symbol in symbols:
        for slide, spec in SLIDE_SPECS.items():
            try:
                bars = alpaca.get_bars(symbol, timeframe=spec.timeframe, start=now - spec.lookback, end=now)
                core.market_data.save(symbol=symbol, slide=slide, bars=_bars_to_json(bars))
            except Exception:
                logger.exception("stock bar sync failed for symbol=%s slide=%s", symbol, slide)

    core.market_data.replace_selection(set(symbols))
    return symbols
