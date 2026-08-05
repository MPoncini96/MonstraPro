"""Builds the idle screen's per-stock view: one of the 5 currently-tracked
symbols, shown as 3 slides (last hour / last trading day / last year),
built from real Alpaca OHLC bars cached in device_core.MarketDataCache -
see trading_worker/stock_bar_sync.py for what selects the 5 symbols and
fetches/refreshes their bars. display does no selection or fetching of its
own; it only reads whatever's currently cached.

portfolio_weight and owned_by are read from data that IS fully per-bot
(each bot's own target_weights - see bot_view.py's module docstring on why
executed trades are not), so unlike a dollar trade amount these are safe
to attribute: "which active bots currently target this symbol" is exactly
what each bot's own latest allocation row says, no netting involved.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime

from device_core.core import DeviceCore

from display.candles import Candle
from display.timeutil import as_utc

SLIDES: tuple[str, ...] = ("1h", "1d", "1y")
SLIDE_LABELS: dict[str, str] = {
    "1h": "Last hour",
    "1d": "Last trading day",
    "1y": "Last year",
}


@dataclass(frozen=True)
class StockView:
    symbol: str
    slide: str
    slide_label: str
    candles: list[Candle] = field(default_factory=list)
    pct_change: float | None = None
    fetched_at: datetime | None = None
    portfolio_weight: float | None = None
    owned_by: list[str] = field(default_factory=list)


def selected_symbols(core: DeviceCore) -> list[str]:
    """The current stock-view selection - trading_worker.stock_bar_sync
    owns picking which symbols to track (top 3 by position size + top 2 by
    prior-day movement); display just shows whatever it selected."""
    return core.market_data.list_symbols()


def _bars_to_candles(bars: list[dict]) -> list[Candle]:
    return [
        Candle(
            bucket_start=as_utc(datetime.fromisoformat(bar["ts"])),
            open=bar["open"],
            high=bar["high"],
            low=bar["low"],
            close=bar["close"],
        )
        for bar in bars
    ]


def _pct_change(bars: list[dict]) -> float | None:
    if not bars:
        return None
    first_open = bars[0]["open"]
    last_close = bars[-1]["close"]
    if first_open == 0:
        return None
    return (last_close - first_open) / first_open


def _portfolio_weight(core: DeviceCore, symbol: str) -> float | None:
    position = core.positions.latest_by_symbol().get(symbol)
    if position is None:
        return None
    snapshots = core.account_snapshots.recent(limit=1)
    if not snapshots:
        return None
    equity = float(snapshots[0]["equity"])
    if equity <= 0:
        return None
    return float(position["market_value"]) / equity


def _owned_by(core: DeviceCore, symbol: str) -> list[str]:
    owners = []
    for row in core.strategies.get_active():
        bot_slug = row["bot_slug"]
        allocation = core.allocations.latest(bot_slug)
        target_weights = (allocation or {}).get("target_weights_json") or {}
        if target_weights.get(symbol, 0.0) > 0:
            owners.append(row.get("display_name") or bot_slug)
    return owners


def build_stock_view(core: DeviceCore, symbol: str, slide: str) -> StockView:
    cached = core.market_data.get(symbol, slide)
    bars = (cached or {}).get("bars_json") or []

    return StockView(
        symbol=symbol,
        slide=slide,
        slide_label=SLIDE_LABELS[slide],
        candles=_bars_to_candles(bars),
        pct_change=_pct_change(bars),
        fetched_at=as_utc(cached["fetched_at"]) if cached and cached.get("fetched_at") else None,
        portfolio_weight=_portfolio_weight(core, symbol),
        owned_by=_owned_by(core, symbol),
    )
