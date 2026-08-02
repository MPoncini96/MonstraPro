"""Buckets the account_snapshot equity time series into OHLC candles for
the idle screen's connected-Alpaca-account performance chart.

Design choice: `DEFAULT_BUCKET_SECONDS` is 300 (5 minutes), not the ~60s
cadence trading_worker now polls Alpaca account equity at (see
services/trading_worker/src/trading_worker/main.py's
ACCOUNT_SNAPSHOT_INTERVAL_SECONDS). A 1-minute bucket would only ever
contain a single sample per candle - open == high == low == close, no real
body or wick, just a flat tick. Bucketing several ~60s samples per candle
instead produces real OHLC shape, while the *rightmost* (still-forming)
candle keeps extending every time a new snapshot lands - which is what
"updated every minute or so" means for this chart in practice: new data
appears roughly every minute, not that every candle spans exactly one
minute.

Pure and hardware-free, like state.py/snapshot.py - `build_candles` takes
plain dicts (the shape AccountSnapshotRepository.recent() returns) and
returns plain Candle values, no pygame/rendering dependency.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

from display.timeutil import as_utc

DEFAULT_BUCKET_SECONDS = 300
DEFAULT_MAX_CANDLES = 20


@dataclass(frozen=True)
class Candle:
    bucket_start: datetime
    open: float
    high: float
    low: float
    close: float


def build_candles(
    snapshots: list[dict[str, Any]],
    *,
    value_key: str = "equity",
    bucket_seconds: int = DEFAULT_BUCKET_SECONDS,
    max_candles: int = DEFAULT_MAX_CANDLES,
) -> list[Candle]:
    """`snapshots` must have "ts" (datetime) and a numeric `value_key` key -
    AccountSnapshotRepository.recent()'s shape by default ("equity"), but
    generic enough to bucket any (ts, value) series the same way: pass
    value_key="value" for BotValueSnapshotRepository.history(), or
    value_key="current_price" for PositionSnapshotRepository.history() -
    see display/bot_view.py and display/stock_view.py. Most-recent-first
    input order is fine (this function sorts defensively rather than
    trusting caller order).

    Returns candles oldest-first (how a chart reads left-to-right), capped
    to the most recent `max_candles` buckets - older history is dropped,
    never silently averaged in, so the visible chart is always a clean
    recent window rather than a compressed whole history.
    """
    if not snapshots:
        return []

    ordered = sorted(snapshots, key=lambda row: as_utc(row["ts"]))

    bucket_values: dict[int, list[float]] = {}
    bucket_starts: dict[int, datetime] = {}
    for row in ordered:
        ts = as_utc(row["ts"])
        bucket_key = int(ts.timestamp() // bucket_seconds)
        bucket_values.setdefault(bucket_key, []).append(float(row[value_key]))
        bucket_starts.setdefault(
            bucket_key, datetime.fromtimestamp(bucket_key * bucket_seconds, tz=timezone.utc)
        )

    candles = [
        Candle(
            bucket_start=bucket_starts[key],
            open=values[0],
            high=max(values),
            low=min(values),
            close=values[-1],
        )
        for key, values in sorted(bucket_values.items())
    ]
    return candles[-max_candles:]
