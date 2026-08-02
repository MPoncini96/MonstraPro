"""Thin wrapper around alpaca-py's TradingClient.

Deliberately minimal: get account equity/cash, list current position market
values, and submit market orders. No retry/backoff, no order-status polling
loop, no session/workflow state machine — this is the "direct calls to
Alpaca's Trading API" ARCHITECTURE.md section 4.1 describes, not a port of
NextJS_Monsta's multi-phase alpacaRebalanceWorkflow (that complexity exists
there to serialize concurrent multi-tenant rebalances across many users'
accounts sharing one process; a Pro Box only ever manages its single owner's
account, so there's nothing to serialize against).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from alpaca.trading.client import TradingClient
from alpaca.trading.enums import OrderSide, TimeInForce
from alpaca.trading.requests import MarketOrderRequest


@dataclass(frozen=True)
class AccountSnapshot:
    equity: float
    cash: float


@dataclass(frozen=True)
class PositionInfo:
    """Richer per-position data than list_position_values()'s bare
    symbol->market_value mapping - unrealized_pl/unrealized_plpc and
    unrealized_intraday_plpc come straight from Alpaca's own Position
    object (computed from real fill data), not derived locally. Feeds
    device_core's position_snapshot table, which powers display's
    last-trade P&L and top-movers stock chart - see
    packages/device_core/src/device_core/db/models.py's PositionSnapshot
    docstring."""

    symbol: str
    qty: float
    avg_entry_price: float
    current_price: float
    market_value: float
    unrealized_pl: float
    unrealized_plpc: float
    unrealized_intraday_plpc: float


@dataclass(frozen=True)
class OrderResult:
    alpaca_order_id: str
    status: str
    raw: dict[str, Any]


class AlpacaClient:
    def __init__(self, *, api_key: str, api_secret: str, base_url: str) -> None:
        # alpaca-py's `paper` flag only controls which of its two hardcoded
        # base URLs it targets; `base_url` from device_core's
        # alpaca_credentials row (paper vs live) is the source of truth, so
        # derive `paper` from it rather than threading a second flag through
        # every caller.
        paper = "paper" in base_url
        self._client = TradingClient(api_key, api_secret, paper=paper)

    def get_account(self) -> AccountSnapshot:
        account = self._client.get_account()
        return AccountSnapshot(equity=float(account.equity), cash=float(account.cash))

    def list_position_values(self) -> dict[str, float]:
        """symbol -> current market value (dollars), for every open position."""
        positions = self._client.get_all_positions()
        return {position.symbol: float(position.market_value) for position in positions}

    def list_positions(self) -> list[PositionInfo]:
        """Every open position, with unrealized P&L - additive alongside
        list_position_values() (rebalance.py's existing caller), not a
        replacement for it."""
        positions = self._client.get_all_positions()
        return [
            PositionInfo(
                symbol=position.symbol,
                qty=float(position.qty),
                avg_entry_price=float(position.avg_entry_price),
                current_price=float(position.current_price),
                market_value=float(position.market_value),
                unrealized_pl=float(position.unrealized_pl),
                unrealized_plpc=float(position.unrealized_plpc),
                unrealized_intraday_plpc=float(position.unrealized_intraday_plpc),
            )
            for position in positions
        ]

    def submit_order(
        self, *, symbol: str, side: str, qty: float | None = None, notional: float | None = None
    ) -> OrderResult:
        if (qty is None) == (notional is None):
            raise ValueError("exactly one of qty or notional must be set")

        order_side = OrderSide.BUY if side == "buy" else OrderSide.SELL
        request = MarketOrderRequest(
            symbol=symbol,
            side=order_side,
            time_in_force=TimeInForce.DAY,
            qty=qty,
            notional=notional,
        )
        order = self._client.submit_order(request)
        return OrderResult(
            alpaca_order_id=str(order.id),
            status=str(order.status.value if hasattr(order.status, "value") else order.status),
            raw=order.model_dump(mode="json"),
        )
