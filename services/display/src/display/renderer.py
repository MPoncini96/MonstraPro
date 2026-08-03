"""Renderer interface — the hardware boundary ARCHITECTURE.md section 1
calls for ("Anything hardware-specific... sits behind an interface so the
same code can later run on an Intel mini PC, a Compute Module, or in
Docker"). `state.py`/`snapshot.py`/`main.py`'s loop only depend on this
Protocol, never on pygame directly.
"""

from __future__ import annotations

from typing import Protocol

from display.bot_view import BotView
from display.last_trade import LastTradeInfo
from display.snapshot import DisplaySnapshot
from display.stock_view import StockView


class Renderer(Protocol):
    def init(self) -> None:
        """Open the window/framebuffer. Called once at startup."""
        ...

    def render_idle(
        self,
        snapshot: DisplaySnapshot,
        last_trade: LastTradeInfo | None,
        banner: str | None,
        *,
        local_pin: str | None = None,
    ) -> None:
        """The idle screen's portfolio phase (idle_rotation.IdlePhase.PORTFOLIO)
        - equity header, last-trade line, and the account-level candle
        chart. See render_idle_bot/render_idle_stock for the other two
        phases in the rotation. `local_pin` (device_core `device.local_pin`)
        is shown as a small footer so the owner can reach
        services/portfolio_web's local page - None suppresses it."""
        ...

    def render_idle_bot(self, view: BotView, banner: str | None, *, local_pin: str | None = None) -> None: ...

    def render_idle_stock(self, view: StockView, banner: str | None, *, local_pin: str | None = None) -> None: ...

    def render_wifi_setup(self, ap_ssid: str | None, setup_url: str | None, banner: str | None) -> None: ...

    def render_awaiting_activation(
        self, device_serial: str | None, pairing_code: str | None, banner: str | None
    ) -> None:
        """pairing_code is what the owner types into monstra.pro's
        /dashboard/devices/pair; device_serial is shown only as a small
        reference line (see trading_worker.activation.HTTPActivationClient
        for where pairing_code comes from)."""
        ...

    def render_trade_wake(self, snapshot: DisplaySnapshot, banner: str | None) -> None: ...

    def pump_events(self) -> bool:
        """Process OS/window events. Returns False if the renderer wants
        the service to exit (e.g. the dev window was closed) — a real
        framebuffer/KMSDRM target never has a reason to return False."""
        ...

    def shutdown(self) -> None: ...
