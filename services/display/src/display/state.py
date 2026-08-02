"""Display state machine — hardware-free, driven entirely by device_event
rows polled from device_core.events (ARCHITECTURE.md section 4.2).

Screen states (mutually exclusive, one active at a time):
    idle                default: portfolio value, today's P/L, market
                         open/closed, last sync time, bot/trade activity.
    wifi_setup:          first-boot Wi-Fi onboarding is in progress
                         (services/device_agent) - "Connect your phone to
                         <ap_ssid> / Then visit <setup_url>". Entered on
                         `wifi_onboarding_started`, left for idle once
                         `wifi_connected` arrives while this screen is
                         active. device_agent knows nothing about
                         activation/pairing - once idle, trading_worker's
                         own `awaiting_activation` event (already emitted
                         once it can reach monstra.pro) supersedes idle on
                         its own, which is how this screen hands off to
                         "device registration and pairing-code status".
    awaiting_activation: "activate this device at monstra.pro" + the
                         device's pairing code.
    trade_wake:          a trade just executed; rotates through recent
                         trades for TRADE_WAKE_DURATION_SECONDS, then falls
                         back to idle.

Connection banner (independent of the active state — rendered as an
overlay, per ARCHITECTURE.md: "not a state of its own"):
    None | "wifi_disconnected" | "alpaca_disconnected" | "update_available"
This one is persistent: it stays until the matching *_connected/applied
event clears it, because it represents an ongoing problem.

Notification banner: a separate, transient overlay for updater-sourced
`notification` events (Objectives.txt: "new bots, or update required...
banners fed into the display loop"). Unlike the connection banner, nothing
explicitly clears this - it auto-expires after
NOTIFICATION_DURATION_SECONDS, same shape as trade_wake's timeout. Kept
distinct from `banner` rather than overloading one field: a Wi-Fi outage
shouldn't get silently replaced by a "new bot available" notice, or vice
versa - main.py's renderer call sites show whichever is more urgent
(connection banner) when both are set.

Nothing here touches pygame or any rendering backend — `advance()` is a
pure function of (current StateMachine, list of new device_event dicts,
now) so it's fully unit-testable without a display attached.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta
from enum import StrEnum
from typing import Any

TRADE_WAKE_DURATION_SECONDS = 30 * 60
NOTIFICATION_DURATION_SECONDS = 10 * 60


class ScreenState(StrEnum):
    IDLE = "idle"
    WIFI_SETUP = "wifi_setup"
    AWAITING_ACTIVATION = "awaiting_activation"
    TRADE_WAKE = "trade_wake"


# device_event types that set/clear the connection banner. "Set" events map
# to the banner they raise; "clear" events (the *_connected counterpart)
# drop the banner they'd otherwise raise.
_BANNER_SET_EVENTS = {
    "wifi_disconnected": "wifi_disconnected",
    "alpaca_disconnected": "alpaca_disconnected",
    "update_available": "update_available",
}
_BANNER_CLEAR_EVENTS = {
    "wifi_connected": "wifi_disconnected",
    "alpaca_connected": "alpaca_disconnected",
    "update_applied": "update_available",
}


@dataclass
class StateMachine:
    screen: ScreenState = ScreenState.IDLE
    banner: str | None = None
    device_serial: str | None = None
    ap_ssid: str | None = None
    setup_url: str | None = None
    recent_trades: list[dict[str, Any]] = field(default_factory=list)
    trade_wake_until: datetime | None = None
    notification: str | None = None
    notification_until: datetime | None = None

    @property
    def top_banner(self) -> str | None:
        """What the renderer should show in the banner strip: the
        persistent connection banner takes priority over a transient
        notification when both are set."""
        return self.banner or self.notification

    def advance(self, events: list[dict[str, Any]], *, now: datetime) -> "StateMachine":
        """Return a new StateMachine reflecting `events` applied in order.

        `events` must be in publish order (oldest first) — the same order
        DeviceEventRepository.list_unconsumed() already returns them in.
        """
        screen = self.screen
        banner = self.banner
        device_serial = self.device_serial
        ap_ssid = self.ap_ssid
        setup_url = self.setup_url
        recent_trades = list(self.recent_trades)
        trade_wake_until = self.trade_wake_until
        notification = self.notification
        notification_until = self.notification_until

        for event in events:
            event_type = event.get("type")
            payload = event.get("payload_json") or {}

            # Banner set/clear is independent of screen transitions below -
            # split into its own if/elif so an event (e.g. wifi_connected)
            # can both clear a banner *and* drive a screen change.
            if event_type in _BANNER_SET_EVENTS:
                banner = _BANNER_SET_EVENTS[event_type]
            elif event_type in _BANNER_CLEAR_EVENTS:
                if banner == _BANNER_CLEAR_EVENTS[event_type]:
                    banner = None

            if event_type == "wifi_onboarding_started":
                screen = ScreenState.WIFI_SETUP
                ap_ssid = payload.get("ap_ssid", ap_ssid)
                setup_url = payload.get("setup_url", setup_url)
            elif event_type == "wifi_connected" and screen == ScreenState.WIFI_SETUP:
                screen = ScreenState.IDLE
            elif event_type == "awaiting_activation":
                screen = ScreenState.AWAITING_ACTIVATION
                device_serial = payload.get("device_serial", device_serial)
            elif event_type == "device_activated":
                if screen == ScreenState.AWAITING_ACTIVATION:
                    screen = ScreenState.IDLE
            elif event_type == "trade_executed":
                screen = ScreenState.TRADE_WAKE
                trade_wake_until = now + timedelta(seconds=TRADE_WAKE_DURATION_SECONDS)
                recent_trades = ([payload] + recent_trades)[:10]
            elif event_type == "notification":
                notification = payload.get("message") or payload.get("banner")
                notification_until = now + timedelta(seconds=NOTIFICATION_DURATION_SECONDS)

        if screen == ScreenState.TRADE_WAKE and trade_wake_until is not None and now >= trade_wake_until:
            screen = ScreenState.IDLE

        if notification is not None and notification_until is not None and now >= notification_until:
            notification = None
            notification_until = None

        return StateMachine(
            screen=screen,
            banner=banner,
            device_serial=device_serial,
            ap_ssid=ap_ssid,
            setup_url=setup_url,
            recent_trades=recent_trades,
            trade_wake_until=trade_wake_until,
            notification=notification,
            notification_until=notification_until,
        )
