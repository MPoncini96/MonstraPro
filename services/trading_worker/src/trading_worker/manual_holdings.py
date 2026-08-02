"""Acquires locked individual-stock positions the owner added via
services/portfolio_web (device_core.db.models.ManualHolding), and NEVER
sells them - see that model's docstring for what "locked" means and
loop.py's module docstring for how bots are kept from touching these
symbols at all.

Idempotent and safe to call every cycle: only ever buys the shortfall
between a holding's target_qty and however many shares are *currently*
held, checked against Alpaca's own live position data rather than an
internal status flag - so it can never drift out of sync with reality.
Once target_qty is reached, calling this again is a no-op for that
symbol. Removing a manual_holding row (services/portfolio_web) simply
stops this function from tracking that symbol going forward; it never
triggers a sell.
"""

from __future__ import annotations

import logging
from typing import Any

from device_core.core import DeviceCore

from trading_worker.alpaca_client import AlpacaClient

logger = logging.getLogger(__name__)

# Ignores sub-share rounding noise (e.g. a fractional share held from a
# prior notional order) rather than treating it as a real shortfall to buy.
MIN_SHORTFALL_QTY = 0.0001


def reconcile_manual_holdings(core: DeviceCore, alpaca: AlpacaClient) -> list[dict[str, Any]]:
    holdings = core.manual_holdings.list_all()
    if not holdings:
        return []

    current_qty_by_symbol = {position.symbol: position.qty for position in alpaca.list_positions()}
    orders_submitted: list[dict[str, Any]] = []

    for holding in holdings:
        symbol = holding["symbol"]
        current_qty = current_qty_by_symbol.get(symbol, 0.0)
        shortfall = holding["target_qty"] - current_qty
        if shortfall <= MIN_SHORTFALL_QTY:
            continue

        order_result = alpaca.submit_order(symbol=symbol, side="buy", qty=shortfall)
        core.orders.record(
            bot_slug="manual",
            symbol=symbol,
            side="buy",
            qty=shortfall,
            status=order_result.status,
            alpaca_order_id=order_result.alpaca_order_id,
            raw_response=order_result.raw,
        )
        orders_submitted.append({"symbol": symbol, "side": "buy", "qty": shortfall})
        logger.info("submitted buy for locked holding symbol=%s qty=%s", symbol, shortfall)

    return orders_submitted
