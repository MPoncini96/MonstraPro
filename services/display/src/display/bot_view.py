"""Builds the idle screen's per-bot view: what this algorithm is doing right
now, its current target allocation, and its own latest rebalance decision.

No longer includes a candlestick chart (dropped per owner request - only
the portfolio-level chart remains) and no longer reads BotValueSnapshot
history.

latest_action is deliberately NOT an executed trade with a dollar amount.
trading_worker nets every active bot's desired trades into one combined
order per symbol before submitting to Alpaca (see
trading_worker/loop.py's module docstring on NETTED_ORDER_BOT_SLUG) - once
netted, a fill can no longer be attributed to the one bot that wanted it,
so there is no truthful per-bot dollar figure to show. What IS genuinely
per-bot and unaffected by netting is each bot's own target_weights history
(loop.py: "each bot's own signals, state, and target_weights history ...
remain fully per-bot and unaffected"). latest_action is derived from the
single largest change between a bot's two most recent target_weights
snapshots - the direction (buy/sell) and symbol are this bot's own
decision, honestly reported; there is no dollar amount attached because
none is attributable to it alone.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from device_core.core import DeviceCore
from strategy_engine.registry import get_algorithm

_WEIGHT_CHANGE_EPSILON = 1e-9


@dataclass(frozen=True)
class LatestAction:
    side: str  # "buy" | "sell"
    symbol: str
    status: str  # "Pending" | "Completed"


@dataclass(frozen=True)
class BotView:
    bot_slug: str
    display_name: str | None
    algorithm_family: str | None
    latest_signal: str | None
    status: str  # "REBALANCING" | "BUYING" | "SELLING" | "WAITING" | "IDLE"
    target_weights: dict[str, float] = field(default_factory=dict)
    latest_action: LatestAction | None = None


def _derive_latest_action(core: DeviceCore, bot_slug: str) -> LatestAction | None:
    """The single biggest target-weight change between this bot's two most
    recent allocations - a stand-in for "what did this bot just decide to
    do" that stays truthful under order netting (see module docstring).
    status is a best-effort read of whether the account's real position
    for that symbol already reflects the decision (Completed) or hasn't
    caught up yet (Pending) - not proof this bot's own order filled, since
    another bot could hold/trade the same symbol too."""
    history = core.allocations.history(bot_slug, limit=2)
    if not history:
        return None

    latest_weights = dict(history[0].get("target_weights_json") or {})
    previous_weights = dict(history[1].get("target_weights_json") or {}) if len(history) > 1 else {}

    symbols = set(latest_weights) | set(previous_weights)
    deltas = {
        symbol: latest_weights.get(symbol, 0.0) - previous_weights.get(symbol, 0.0) for symbol in symbols
    }
    if not deltas:
        return None

    # Tie-break deterministically (a straight swap - one symbol out, another
    # in at the same weight - has two equal-magnitude deltas): prefer the
    # buy side, then alphabetical. Without this, iterating `deltas` (built
    # from a set) breaks ties by Python's per-process string hash order,
    # which flips depending on PYTHONHASHSEED - the same input could report
    # "buy" in one run and "sell" in another.
    symbol, delta = max(deltas.items(), key=lambda item: (abs(item[1]), item[1] > 0, item[0]))
    if abs(delta) < _WEIGHT_CHANGE_EPSILON:
        return None

    side = "buy" if delta > 0 else "sell"
    position = core.positions.latest_by_symbol().get(symbol)
    currently_held = bool(position and (position.get("qty") or 0) != 0)
    reflects_decision = currently_held if side == "buy" else not currently_held
    status = "Completed" if reflects_decision else "Pending"

    return LatestAction(side=side, symbol=symbol, status=status)


def _derive_status(latest_signal: str | None, latest_action: LatestAction | None) -> str:
    if latest_signal == "REBALANCE":
        if latest_action is None:
            return "REBALANCING"
        return "BUYING" if latest_action.side == "buy" else "SELLING"
    if latest_signal is not None:
        return "WAITING"
    return "IDLE"


def build_bot_view(core: DeviceCore, bot_slug: str) -> BotView:
    row = core.strategies.get(bot_slug)

    # bot_type (the engine family, e.g. "force") can differ from bot_slug
    # (a specific monster variation's per-instance identity, e.g.
    # "vectura_draco") for monstra.pro-synced rows - fall back to bot_slug
    # only for rows that predate that sync, same convention loop.py uses.
    engine_slug = (row or {}).get("bot_type") or bot_slug
    algorithm = get_algorithm(engine_slug)
    bot_type = algorithm.bot_type if algorithm is not None else engine_slug
    algorithm_family = algorithm.display_name if algorithm is not None else None
    latest_signal_row = core.signals.latest(bot_slug, bot_type)
    latest_signal = latest_signal_row["signal"] if latest_signal_row else None

    allocation = core.allocations.latest(bot_slug)
    target_weights = dict((allocation or {}).get("target_weights_json") or {})

    latest_action = _derive_latest_action(core, bot_slug)

    return BotView(
        bot_slug=bot_slug,
        display_name=(row or {}).get("display_name"),
        algorithm_family=algorithm_family,
        latest_signal=latest_signal,
        status=_derive_status(latest_signal, latest_action),
        target_weights=target_weights,
        latest_action=latest_action,
    )
