"""Builds the idle screen's per-bot performance view: the bot's latest
signal plus its BotValueSnapshot history, bucketed into candles the same
way the portfolio view buckets account_snapshot - see
device_core.db.models.BotValueSnapshot's docstring for exactly what
"value" means here (a target-weighted price index, not a dollar amount
actually invested - Alpaca doesn't segregate positions by originating
bot).
"""

from __future__ import annotations

from dataclasses import dataclass, field

from device_core.core import DeviceCore
from strategy_engine.registry import get_algorithm

from display.candles import Candle, build_candles


@dataclass(frozen=True)
class BotView:
    bot_slug: str
    display_name: str | None
    latest_signal: str | None
    candles: list[Candle] = field(default_factory=list)


def build_bot_view(core: DeviceCore, bot_slug: str) -> BotView:
    row = core.strategies.get(bot_slug)
    algorithm = get_algorithm(bot_slug)
    bot_type = algorithm.bot_type if algorithm is not None else bot_slug
    latest_signal = core.signals.latest(bot_slug, bot_type)

    history = core.bot_values.history(bot_slug)
    candles = build_candles(history, value_key="value")

    return BotView(
        bot_slug=bot_slug,
        display_name=(row or {}).get("display_name"),
        latest_signal=latest_signal["signal"] if latest_signal else None,
        candles=candles,
    )
