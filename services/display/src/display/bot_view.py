"""Builds the idle screen's per-bot performance view: the bot's latest
signal, its full current target-weights breakdown (every stock it's
currently signaling, not just the latest signal word), and the device's
most recent trade activity.

No longer includes a candlestick chart (dropped per owner request - only
the portfolio-level chart remains) and no longer reads BotValueSnapshot
history.

recent_orders is the device's overall last-8 trades, not this bot's own -
once bots' trades are netted together in the same cycle, a combined order
can no longer be attributed to one originating bot (see
trading_worker/loop.py's module docstring on NETTED_ORDER_BOT_SLUG), so
there's no real per-bot trade history to show here instead.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from device_core.core import DeviceCore
from strategy_engine.registry import get_algorithm

RECENT_ORDERS_LIMIT = 8


@dataclass(frozen=True)
class BotView:
    bot_slug: str
    display_name: str | None
    latest_signal: str | None
    target_weights: dict[str, float] = field(default_factory=dict)
    recent_orders: list[dict[str, Any]] = field(default_factory=list)


def build_bot_view(core: DeviceCore, bot_slug: str) -> BotView:
    row = core.strategies.get(bot_slug)

    # bot_type (the engine family, e.g. "force") can differ from bot_slug
    # (a specific monster variation's per-instance identity, e.g.
    # "vectura_draco") for monstra.pro-synced rows - fall back to bot_slug
    # only for rows that predate that sync, same convention loop.py uses.
    engine_slug = (row or {}).get("bot_type") or bot_slug
    algorithm = get_algorithm(engine_slug)
    bot_type = algorithm.bot_type if algorithm is not None else engine_slug
    latest_signal = core.signals.latest(bot_slug, bot_type)

    allocation = core.allocations.latest(bot_slug)
    target_weights = dict((allocation or {}).get("target_weights_json") or {})

    recent_orders = core.orders.recent(limit=RECENT_ORDERS_LIMIT)

    return BotView(
        bot_slug=bot_slug,
        display_name=(row or {}).get("display_name"),
        latest_signal=latest_signal["signal"] if latest_signal else None,
        target_weights=target_weights,
        recent_orders=recent_orders,
    )
