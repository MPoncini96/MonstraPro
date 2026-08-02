"""One trading cycle: run every active strategy_config row through
strategy_engine, act on REBALANCE signals, persist everything.

Each bot's target weights are diffed against current Alpaca positions
independently — there's no cross-bot portfolio netting (e.g. bot A selling
a symbol bot B is simultaneously buying). ARCHITECTURE.md section 10 lists
"multi-strategy portfolio blending beyond what a single owner's configured
bot(s) produce" as explicitly deferred past V1, so this matches the current
scope rather than being an oversight.

One bot's failure doesn't abort the cycle for the others — each bot's
handling is wrapped and logged independently via device_core.logs.

Locked manual holdings (device_core.db.models.ManualHolding, added via
services/portfolio_web) are excluded from every bot's rebalance math here:
a locked symbol is dropped from the bot's own target_weights (renormalized
- see rebalance.exclude_locked_symbols), from what the bot sees as
"current positions" to reconcile against, and its market value is
subtracted from the equity the bot is allowed to allocate against. Without
this, a locked symbol with no corresponding target weight looks - to
compute_order_plan alone - exactly like a position the bot should fully
exit; see test_rebalance.py's
test_locked_position_would_otherwise_be_sold_without_exclusion for the
concrete failure mode this prevents. Acquiring a locked holding in the
first place (buying up to target_qty) is a separate, one-directional
code path - see trading_worker/manual_holdings.py's
reconcile_manual_holdings, the only thing allowed to trade a locked symbol.

Known gap: `_run_one_bot` below looks up the strategy_engine runner via
`get_algorithm(bot_slug)`/`get_runner(bot_slug)`, i.e. it assumes
strategy_config.bot_slug IS one of the three engine slugs ("force"/
"aptet"/"draco"). NextJS_Monsta's bot-picker (Track B2) actually persists
`bot_slug` as a specific monster variation's slug (e.g. "vectura_draco",
the per-instance identity for signal/state/order tracking) with a
*separate* `botType` field carrying the engine - see
services/updater/src/updater/manifest_client.py's module docstring. Once
whatever provisions local strategy_config rows from that data exists, this
needs to route via a stored engine/algorithm_slug field instead of
bot_slug directly. Not fixed yet because nothing populates strategy_config
from real B-side data today - tracked here rather than silently wrong.
"""

from __future__ import annotations

import logging
from typing import Any

from device_core.core import DeviceCore
from device_core.events import EventType
from strategy_engine.registry import get_algorithm, get_runner

from trading_worker.alpaca_client import AlpacaClient
from trading_worker.rebalance import compute_order_plan, exclude_locked_symbols

logger = logging.getLogger(__name__)


def _run_one_bot(
    core: DeviceCore,
    alpaca: AlpacaClient,
    *,
    bot_slug: str,
    params: dict[str, Any],
    equity_history: list[float],
    locked_symbols: set[str],
) -> dict[str, Any]:
    algorithm = get_algorithm(bot_slug)
    runner = get_runner(bot_slug) if algorithm is not None else None
    if runner is None:
        raise ValueError(f"No strategy_engine runner registered for bot_slug={bot_slug!r}")

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

    orders_submitted: list[dict[str, Any]] = []
    target_weights = (result.get("payload") or {}).get("target_weights") or {}

    if result["signal"] == "REBALANCE" and target_weights:
        safe_target_weights = exclude_locked_symbols(target_weights, locked_symbols)
        if safe_target_weights != target_weights:
            logger.warning(
                "bot_slug=%s target_weights touched a locked symbol; excluded and renormalized",
                bot_slug,
            )
        if not safe_target_weights:
            # Every target symbol is locked - nothing left for this bot to
            # safely trade this cycle. Not an error: skip the rebalance
            # entirely rather than trading a meaningless empty basket.
            return {"bot_slug": bot_slug, "signal": result["signal"], "orders": []}

        account = alpaca.get_account()
        all_position_values = alpaca.list_position_values()
        locked_value = sum(value for symbol, value in all_position_values.items() if symbol in locked_symbols)
        manageable_position_values = {
            symbol: value for symbol, value in all_position_values.items() if symbol not in locked_symbols
        }
        manageable_equity = max(account.equity - locked_value, 0.0)

        order_plan = compute_order_plan(
            target_weights=safe_target_weights,
            current_position_values=manageable_position_values,
            account_equity=manageable_equity,
        )

        current_total = sum(manageable_position_values.values()) or manageable_equity
        current_weights = (
            {symbol: value / current_total for symbol, value in manageable_position_values.items()}
            if current_total > 0
            else {}
        )
        core.allocations.replace(
            bot_slug=bot_slug, target_weights=safe_target_weights, current_weights=current_weights
        )

        for item in order_plan:
            order_result = alpaca.submit_order(symbol=item.symbol, side=item.side, notional=item.notional)
            core.orders.record(
                bot_slug=bot_slug,
                symbol=item.symbol,
                side=item.side,
                notional=item.notional,
                status=order_result.status,
                alpaca_order_id=order_result.alpaca_order_id,
                raw_response=order_result.raw,
            )
            orders_submitted.append({"symbol": item.symbol, "side": item.side, "notional": item.notional})

        if orders_submitted:
            core.events.publish(EventType.TRADE_EXECUTED, {"bot_slug": bot_slug, "orders": orders_submitted})

    return {"bot_slug": bot_slug, "signal": result["signal"], "orders": orders_submitted}


def run_cycle(core: DeviceCore, alpaca: AlpacaClient) -> list[dict[str, Any]]:
    account = alpaca.get_account()
    core.account_snapshots.record(equity=account.equity, cash=account.cash)
    equity_history = core.account_snapshots.equity_history()
    locked_symbols = {row["symbol"] for row in core.manual_holdings.list_all()}

    results: list[dict[str, Any]] = []
    for row in core.strategies.get_active():
        bot_slug = row["bot_slug"]
        try:
            result = _run_one_bot(
                core,
                alpaca,
                bot_slug=bot_slug,
                params=row.get("params_json") or {},
                equity_history=equity_history,
                locked_symbols=locked_symbols,
            )
            results.append(result)
        except Exception as exc:  # noqa: BLE001 - one bot's failure must not abort the cycle
            logger.exception("trading cycle failed for bot_slug=%s", bot_slug)
            core.logs.record(
                level="ERROR",
                component="trading_worker",
                message=f"cycle failed for bot_slug={bot_slug}: {exc}",
                context={"bot_slug": bot_slug},
            )
            results.append({"bot_slug": bot_slug, "signal": None, "orders": [], "error": str(exc)})

    return results
