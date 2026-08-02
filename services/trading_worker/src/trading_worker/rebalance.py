"""Diff target portfolio weights against current Alpaca positions to get an
order plan.

Python port of the "diff target allocation vs current holdings, submit
orders" logic in
NextJS_Monsta/src/lib/server/portfolioAutomationRebalanceExecution.ts,
simplified for a single-owner device: no multi-user session/workflow state
machine (see alpaca_client.py's docstring for why), no partial-fill
reconciliation loop — one order plan per trading cycle, submitted directly.

Orders are notional (dollar-denominated), not share-quantity: simpler diff
math, and it means a strategy's target weights map directly to order sizes
regardless of the underlying share price.
"""

from __future__ import annotations

from dataclasses import dataclass

DEFAULT_MIN_TRADE_DOLLARS = 1.0


@dataclass(frozen=True)
class OrderPlanItem:
    symbol: str
    side: str  # "buy" | "sell"
    notional: float


def exclude_locked_symbols(target_weights: dict[str, float], locked_symbols: set[str]) -> dict[str, float]:
    """Drops any locked (device_core.db.models.ManualHolding) symbol from a
    bot's own target_weights and renormalizes the remainder back to sum
    ~1.0, so PortfolioAllocationRepository's weight-sum validation still
    passes and compute_order_plan's dollar math stays correct.

    A bot's strategy_engine algorithm has no concept of locked symbols -
    it computes target_weights purely from its own signal logic, so this
    is the seam that keeps a bot from ever generating a sell (or buy) for
    a symbol the owner explicitly locked, without needing every bot to
    know about manual_holding itself. If every target symbol happens to be
    locked, returns {} - the bot simply doesn't trade this cycle rather
    than trading a shrunken, no-longer-meaningful basket.
    """
    remaining = {symbol: weight for symbol, weight in target_weights.items() if symbol not in locked_symbols}
    total = sum(remaining.values())
    if total <= 0:
        return {}
    return {symbol: weight / total for symbol, weight in remaining.items()}


def compute_order_plan(
    *,
    target_weights: dict[str, float],
    current_position_values: dict[str, float],
    account_equity: float,
    min_trade_dollars: float = DEFAULT_MIN_TRADE_DOLLARS,
) -> list[OrderPlanItem]:
    """Return sells before buys, so a same-cycle sell can fund a buy.

    A symbol currently held but absent from `target_weights` is treated as
    a target of 0 (full exit). Diffs smaller than `min_trade_dollars` are
    dropped to avoid dust-sized orders.
    """
    if account_equity <= 0:
        return []

    target_dollars = {symbol: weight * account_equity for symbol, weight in target_weights.items()}
    all_symbols = set(target_dollars) | set(current_position_values)

    sells: list[OrderPlanItem] = []
    buys: list[OrderPlanItem] = []

    for symbol in sorted(all_symbols):
        target = target_dollars.get(symbol, 0.0)
        current = current_position_values.get(symbol, 0.0)
        diff = target - current

        if abs(diff) < min_trade_dollars:
            continue

        if diff < 0:
            sells.append(OrderPlanItem(symbol=symbol, side="sell", notional=round(-diff, 2)))
        else:
            buys.append(OrderPlanItem(symbol=symbol, side="buy", notional=round(diff, 2)))

    return sells + buys
