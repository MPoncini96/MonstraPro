"""One trading cycle: run every active strategy_config row through
strategy_engine, combine every bot's desired allocation into one netted
order plan, act on it, persist everything.

Each active bot gets a configurable *relative* share of the account
(strategy_config.equity_weight - a positive float, treated as 1.0/equal-
share when unset) instead of assuming it alone owns the whole account.
Every bot's own target_weights (after locked-symbol exclusion) are scaled
into dollar terms by that bot's share of manageable equity, summed
per-symbol across every active bot, and diffed against real current Alpaca
positions exactly once via compute_order_plan - not once per bot. This is
what closes the gap ARCHITECTURE.md section 10 used to list as deferred
("multi-strategy portfolio blending"): before this, two bots independently
deciding to sell the same held symbol in the same cycle would race each
other, and only the first submission would succeed - the rest got hard
"insufficient qty" errors from Alpaca. Caught live on real hardware with 5
active bots sharing one account.

Once bots' trades are netted, a single combined order for a symbol can no
longer be cleanly attributed to one originating bot (bot A wanted to sell
$50, bot B wanted to sell $23 of the same symbol - only one $73 net sell
order exists). Netted orders are recorded under the synthetic bot_slug
NETTED_ORDER_BOT_SLUG rather than any real bot's slug - a deliberate,
visible simplification: per-bot order/trade history disappears for any
trade that got netted with another bot's, while each bot's own signals,
state, and target_weights history (used by main.py's bot-value snapshot
feature) remain fully per-bot and unaffected. Nothing else in this
codebase treats Order.bot_slug as a foreign key into strategy_config, so
this is safe.

One bot's failure doesn't abort the cycle for the others - each bot's
signal computation is wrapped and logged independently via
device_core.logs. A bot that fails (or simply HOLDs) this cycle still
contributes its *last known* desired allocation
(core.allocations.latest(bot_slug)) to the combined pool, re-excluded
against this cycle's current locked-symbol set - otherwise a transient
strategy-engine error, or a bot that just doesn't have a fresh signal this
tick, would force-sell whatever it was previously holding rather than
leaving it in place. This is the same "a safe fallback state is never a
reason to force a change" philosophy used elsewhere in this codebase
(activation.py, alpaca_sync.py).

Locked manual holdings (device_core.db.models.ManualHolding, added via
services/portfolio_web) are excluded from the *combined* rebalance math
here: a locked symbol is dropped from every bot's contributed target
weights (renormalized - see rebalance.exclude_locked_symbols) before
combining, from what the combined pool sees as "current positions" to
reconcile against, and its market value is subtracted from the equity
every bot is allowed to allocate against. Without this, a locked symbol
with no corresponding target weight looks - to compute_order_plan alone -
exactly like a position that should be fully exited; see
test_rebalance.py's test_locked_position_would_otherwise_be_sold_without_exclusion
for the concrete failure mode this prevents. Acquiring a locked holding in
the first place (buying up to target_qty) is a separate, one-directional
code path - see trading_worker/manual_holdings.py's
reconcile_manual_holdings, the only thing allowed to trade a locked symbol.

`_run_one_bot` below looks up the strategy_engine runner via
`get_algorithm(bot_type or bot_slug)`/`get_runner(...)` - `bot_type`
("force"/"aptet"/"draco", the engine family) is a separate field from
`bot_slug` (a specific monster variation's slug, e.g. "vectura_draco", the
per-instance identity used for signal/state tracking), synced from
monstra.pro by trading_worker/bot_selection_sync.py. Falls back to
treating bot_slug itself as the engine slug when bot_type is None, for
rows that predate that sync (local/test-seeded strategy_config rows where
bot_slug already IS one of the three engine slugs directly).
"""

from __future__ import annotations

import logging
from collections import defaultdict
from typing import Any

from device_core.core import DeviceCore
from device_core.events import EventType
from strategy_engine.registry import get_algorithm, get_runner

from trading_worker.alpaca_client import AlpacaClient
from trading_worker.rebalance import compute_order_plan, exclude_locked_symbols

logger = logging.getLogger(__name__)

# Orders that combine more than one bot's contribution are recorded under
# this synthetic bot_slug - see module docstring for why true per-bot
# attribution isn't attempted.
NETTED_ORDER_BOT_SLUG = "_portfolio"


def _run_one_bot(
    core: DeviceCore,
    *,
    bot_slug: str,
    bot_type: str | None = None,
    params: dict[str, Any],
    equity_history: list[float],
    locked_symbols: set[str],
    manageable_position_values: dict[str, float],
    manageable_equity: float,
) -> dict[str, Any]:
    """Computes bot_slug's signal for this cycle and returns its *desired
    allocation* (locked-symbol-excluded, renormalized target_weights) -
    never submits any orders itself. run_cycle combines every active bot's
    desired allocation into one netted order plan; see this module's
    docstring.

    Takes no `alpaca` client at all - `manageable_position_values`/
    `manageable_equity` are computed once in run_cycle from a single
    account/position fetch shared across every bot this cycle, not
    re-fetched per bot (the previous per-bot re-fetch was itself part of
    the race that caused overlapping orders to collide).
    """
    engine_slug = bot_type or bot_slug
    algorithm = get_algorithm(engine_slug)
    runner = get_runner(engine_slug) if algorithm is not None else None
    if runner is None:
        raise ValueError(
            f"No strategy_engine runner registered for bot_slug={bot_slug!r} bot_type={bot_type!r}"
        )

    config = {**params, "bot_id": bot_slug, "equity_history": equity_history}
    prior_state = core.bot_states.get(bot_slug)

    result = runner(config, prior_state)

    core.signals.store(
        bot_id=result["bot_id"],
        bot_type=result["bot_type"],
        signal=result["signal"],
        note=result.get("note"),
        payload=result.get("payload"),
        ts=result.get("ts"),
    )
    core.events.publish(EventType.SIGNAL_GENERATED, {"bot_slug": bot_slug, "signal": result["signal"]})

    updated_state = result.get("state")
    if updated_state is not None:
        core.bot_states.save(bot_slug, updated_state)

    target_weights = (result.get("payload") or {}).get("target_weights") or {}
    desired_weights: dict[str, float] | None = None

    if result["signal"] == "REBALANCE" and target_weights:
        safe_target_weights = exclude_locked_symbols(target_weights, locked_symbols)
        if safe_target_weights != target_weights:
            logger.warning(
                "bot_slug=%s target_weights touched a locked symbol; excluded and renormalized",
                bot_slug,
            )
        if safe_target_weights:
            # current_weights here is account-wide (every bot sees the same
            # non-locked position snapshot this cycle) - purely historical/
            # informational, nothing downstream keys behavior off its
            # specific values (see PortfolioAllocation's own docstring).
            current_total = sum(manageable_position_values.values()) or manageable_equity
            current_weights = (
                {symbol: value / current_total for symbol, value in manageable_position_values.items()}
                if current_total > 0
                else {}
            )
            core.allocations.replace(
                bot_slug=bot_slug, target_weights=safe_target_weights, current_weights=current_weights
            )
            desired_weights = safe_target_weights
        # else: every target symbol is locked - nothing left for this bot
        # to safely trade this cycle. Not an error: desired_weights stays
        # None, so the caller falls back to this bot's last known
        # allocation instead of trading a meaningless empty basket.

    return {"bot_slug": bot_slug, "signal": result["signal"], "desired_weights": desired_weights}


def _last_known_allocation(core: DeviceCore, bot_slug: str, locked_symbols: set[str]) -> dict[str, float]:
    """This bot's most recently persisted target_weights (or {} if it has
    never rebalanced), re-excluded against *this* cycle's locked-symbol
    set - a symbol can be locked after the bot's last real rebalance, so
    re-applying the exclusion here (not just relying on it having been
    applied when the allocation was originally written) prevents a stale
    allocation from reintroducing a now-locked symbol into the combined
    pool."""
    last = core.allocations.latest(bot_slug)
    last_weights = (last or {}).get("target_weights_json") or {}
    return exclude_locked_symbols(last_weights, locked_symbols)


def run_cycle(core: DeviceCore, alpaca: AlpacaClient) -> list[dict[str, Any]]:
    account = alpaca.get_account()
    core.account_snapshots.record(equity=account.equity, cash=account.cash)
    equity_history = core.account_snapshots.equity_history()
    locked_symbols = {row["symbol"] for row in core.manual_holdings.list_all()}

    all_position_values = alpaca.list_position_values()
    locked_value = sum(value for symbol, value in all_position_values.items() if symbol in locked_symbols)
    manageable_position_values = {
        symbol: value for symbol, value in all_position_values.items() if symbol not in locked_symbols
    }
    manageable_equity = max(account.equity - locked_value, 0.0)

    active_rows = core.strategies.get_active()
    results: list[dict[str, Any]] = []
    contributions: list[tuple[dict[str, Any], dict[str, float]]] = []

    for row in active_rows:
        bot_slug = row["bot_slug"]
        try:
            result = _run_one_bot(
                core,
                bot_slug=bot_slug,
                bot_type=row.get("bot_type"),
                params=row.get("params_json") or {},
                equity_history=equity_history,
                locked_symbols=locked_symbols,
                manageable_position_values=manageable_position_values,
                manageable_equity=manageable_equity,
            )
            results.append(result)
            desired_weights = result["desired_weights"]
            if desired_weights is None:
                desired_weights = _last_known_allocation(core, bot_slug, locked_symbols)
        except Exception as exc:  # noqa: BLE001 - one bot's failure must not abort the cycle
            logger.exception("trading cycle failed for bot_slug=%s", bot_slug)
            core.logs.record(
                level="ERROR",
                component="trading_worker",
                message=f"cycle failed for bot_slug={bot_slug}: {exc}",
                context={"bot_slug": bot_slug},
            )
            results.append({"bot_slug": bot_slug, "signal": None, "error": str(exc)})
            desired_weights = _last_known_allocation(core, bot_slug, locked_symbols)

        contributions.append((row, desired_weights))

    total_weight = sum(
        (row.get("equity_weight") if row.get("equity_weight") is not None else 1.0) for row, _ in contributions
    ) or 1.0

    combined_target_values: dict[str, float] = defaultdict(float)
    for row, desired_weights in contributions:
        weight = row.get("equity_weight") if row.get("equity_weight") is not None else 1.0
        bot_equity = manageable_equity * (weight / total_weight)
        for symbol, symbol_weight in desired_weights.items():
            combined_target_values[symbol] += symbol_weight * bot_equity

    combined_target_weights = (
        {symbol: value / manageable_equity for symbol, value in combined_target_values.items()}
        if manageable_equity > 0
        else {}
    )

    order_plan = compute_order_plan(
        target_weights=combined_target_weights,
        current_position_values=manageable_position_values,
        account_equity=manageable_equity,
    )

    orders_submitted: list[dict[str, Any]] = []
    try:
        for item in order_plan:
            order_result = alpaca.submit_order(symbol=item.symbol, side=item.side, notional=item.notional)
            core.orders.record(
                bot_slug=NETTED_ORDER_BOT_SLUG,
                symbol=item.symbol,
                side=item.side,
                notional=item.notional,
                status=order_result.status,
                alpaca_order_id=order_result.alpaca_order_id,
                raw_response=order_result.raw,
            )
            orders_submitted.append({"symbol": item.symbol, "side": item.side, "notional": item.notional})
    except Exception as exc:  # noqa: BLE001 - a submission failure must still return this cycle's signals
        logger.exception("netted order submission failed")
        core.logs.record(
            level="ERROR",
            component="trading_worker",
            message=f"netted order submission failed: {exc}",
        )
        core.events.publish(EventType.FATAL_ERROR, {"component": "trading_worker"}, severity="error")

    if orders_submitted:
        core.events.publish(
            EventType.TRADE_EXECUTED, {"bot_slug": NETTED_ORDER_BOT_SLUG, "orders": orders_submitted}
        )

    return results
