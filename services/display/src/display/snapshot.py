"""Builds the data the idle/trade_wake screens render, reading only from
device_core repositories — no Alpaca calls, no dependency on trading_worker
internals (ARCHITECTURE.md section 4.2: display and trading_worker only
communicate through the DB-backed event log / shared tables).

Known gap: Objectives.txt asks for recent *closed positions* with a
win/loss label. That's deliberately NOT implemented here. `Order` rows only
record submitted notional (dollar) amounts, not filled share quantities or
prices (OrderRepository.mark_filled exists but nothing calls it yet — see
trading_worker/alpaca_client.py). Without quantity/price, there's no sound
way to attribute a given sell's dollar amount to a specific prior buy's
cost basis — a naive proportional-notional approximation was tried and
discarded because it's mathematically incapable of ever reporting a loss
(the ratio of cost-basis to open-notional is invariant under that formula,
so realized P&L computes to ~0 for every ordinary sell). The correct fix is
for trading_worker to either poll Alpaca's order-fill data or pull
per-position realized P&L from Alpaca's account activities API and persist
it — `recent_orders` below is the honest stand-in until that lands: a plain
activity feed (symbol/side/notional/status), no fabricated P&L attached.

Market-open/closed is a local NYSE-hours heuristic (weekday, 9:30-16:00
America/New_York), not a live Alpaca clock call — mirrors the fallback
logic strategy_engine.market_data.provider.is_market_open() uses when
Alpaca isn't configured, chosen so display never needs Alpaca credentials
of its own. Doesn't account for market holidays.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime, time, timezone
from typing import Any
from zoneinfo import ZoneInfo

from device_core.core import DeviceCore
from strategy_engine.registry import get_algorithm

from display.candles import Candle, build_candles
from display.timeutil import as_utc


@dataclass(frozen=True)
class BotPerformance:
    bot_slug: str
    display_name: str | None
    latest_signal: str | None
    latest_note: str | None
    target_weights: dict[str, float]


@dataclass(frozen=True)
class DisplaySnapshot:
    portfolio_equity: float | None
    portfolio_pl_today: float | None
    market_open: bool
    last_sync_at: datetime | None
    bots: list[BotPerformance] = field(default_factory=list)
    recent_orders: list[dict[str, Any]] = field(default_factory=list)
    candles: list[Candle] = field(default_factory=list)


def is_market_open_heuristic(*, now: datetime | None = None) -> bool:
    now_et = (now or datetime.now(timezone.utc)).astimezone(ZoneInfo("America/New_York"))
    session_open = time(9, 30)
    session_close = time(16, 0)
    return now_et.weekday() < 5 and session_open <= now_et.time() <= session_close


def _today_pl(snapshots_newest_first: list[dict[str, Any]], *, today: date) -> float | None:
    """snapshots_newest_first must be ordered most-recent-first (as
    AccountSnapshotRepository.recent() returns them)."""
    if not snapshots_newest_first:
        return None
    latest = snapshots_newest_first[0]
    same_day = [row for row in snapshots_newest_first if as_utc(row["ts"]).date() == today]
    if len(same_day) < 2:
        return None
    earliest_today = same_day[-1]
    return float(latest["equity"]) - float(earliest_today["equity"])


def build_snapshot(core: DeviceCore, *, now: datetime | None = None) -> DisplaySnapshot:
    now = now or datetime.now(timezone.utc)

    snapshots = core.account_snapshots.recent()
    portfolio_equity = float(snapshots[0]["equity"]) if snapshots else None
    portfolio_pl_today = _today_pl(snapshots, today=now.astimezone(timezone.utc).date())
    last_sync_at = as_utc(snapshots[0]["ts"]) if snapshots else None
    candles = build_candles(snapshots)

    bots: list[BotPerformance] = []
    all_orders: list[dict[str, Any]] = []
    for row in core.strategies.get_active():
        bot_slug = row["bot_slug"]
        algorithm = get_algorithm(bot_slug)
        bot_type = algorithm.bot_type if algorithm is not None else bot_slug
        latest_signal = core.signals.latest(bot_slug, bot_type)
        allocation = core.allocations.latest(bot_slug)
        bots.append(
            BotPerformance(
                bot_slug=bot_slug,
                display_name=row.get("display_name"),
                latest_signal=latest_signal["signal"] if latest_signal else None,
                latest_note=latest_signal["note"] if latest_signal else None,
                target_weights=dict((allocation or {}).get("target_weights_json") or {}),
            )
        )
        all_orders.extend(core.orders.recent(bot_slug=bot_slug, limit=50))

    recent_orders = sorted(all_orders, key=lambda o: o["id"], reverse=True)[:20]

    return DisplaySnapshot(
        portfolio_equity=portfolio_equity,
        portfolio_pl_today=portfolio_pl_today,
        market_open=is_market_open_heuristic(now=now),
        last_sync_at=last_sync_at,
        bots=bots,
        recent_orders=recent_orders,
        candles=candles,
    )
