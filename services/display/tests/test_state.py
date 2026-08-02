from datetime import datetime, timedelta, timezone

from display.state import (
    NOTIFICATION_DURATION_SECONDS,
    ScreenState,
    StateMachine,
    TRADE_WAKE_DURATION_SECONDS,
)

_NOW = datetime(2026, 1, 5, 12, 0, 0, tzinfo=timezone.utc)


def _event(event_type: str, payload: dict | None = None) -> dict:
    return {"type": event_type, "payload_json": payload or {}}


def test_initial_state_is_idle_with_no_banner():
    machine = StateMachine()
    assert machine.screen == ScreenState.IDLE
    assert machine.banner is None


def test_awaiting_activation_event_switches_screen_and_captures_serial():
    machine = StateMachine()
    machine = machine.advance([_event("awaiting_activation", {"device_serial": "MPB-ABC123"})], now=_NOW)

    assert machine.screen == ScreenState.AWAITING_ACTIVATION
    assert machine.device_serial == "MPB-ABC123"


def test_device_activated_returns_to_idle_from_awaiting_activation():
    machine = StateMachine(screen=ScreenState.AWAITING_ACTIVATION, device_serial="MPB-ABC123")
    machine = machine.advance([_event("device_activated")], now=_NOW)

    assert machine.screen == ScreenState.IDLE


def test_device_activated_is_a_noop_when_already_idle():
    machine = StateMachine(screen=ScreenState.IDLE)
    machine = machine.advance([_event("device_activated")], now=_NOW)

    assert machine.screen == ScreenState.IDLE


def test_trade_executed_wakes_screen_and_records_trade():
    machine = StateMachine()
    machine = machine.advance([_event("trade_executed", {"bot_slug": "force", "orders": []})], now=_NOW)

    assert machine.screen == ScreenState.TRADE_WAKE
    assert machine.recent_trades == [{"bot_slug": "force", "orders": []}]
    assert machine.trade_wake_until == _NOW + timedelta(seconds=TRADE_WAKE_DURATION_SECONDS)


def test_trade_wake_reverts_to_idle_after_timeout_with_no_new_events():
    machine = StateMachine()
    machine = machine.advance([_event("trade_executed", {"bot_slug": "force"})], now=_NOW)
    assert machine.screen == ScreenState.TRADE_WAKE

    later = _NOW + timedelta(seconds=TRADE_WAKE_DURATION_SECONDS + 1)
    machine = machine.advance([], now=later)

    assert machine.screen == ScreenState.IDLE


def test_trade_wake_stays_active_before_timeout():
    machine = StateMachine()
    machine = machine.advance([_event("trade_executed", {"bot_slug": "force"})], now=_NOW)

    soon = _NOW + timedelta(seconds=TRADE_WAKE_DURATION_SECONDS - 1)
    machine = machine.advance([], now=soon)

    assert machine.screen == ScreenState.TRADE_WAKE


def test_recent_trades_newest_first_capped_at_ten():
    machine = StateMachine()
    events = [_event("trade_executed", {"n": i}) for i in range(15)]
    machine = machine.advance(events, now=_NOW)

    assert len(machine.recent_trades) == 10
    assert machine.recent_trades[0] == {"n": 14}


def test_banner_set_and_cleared_by_matching_events():
    machine = StateMachine()
    machine = machine.advance([_event("wifi_disconnected")], now=_NOW)
    assert machine.banner == "wifi_disconnected"

    machine = machine.advance([_event("wifi_connected")], now=_NOW)
    assert machine.banner is None


def test_banner_persists_across_unrelated_events():
    machine = StateMachine()
    machine = machine.advance([_event("alpaca_disconnected")], now=_NOW)
    machine = machine.advance([_event("trade_executed", {"bot_slug": "force"})], now=_NOW)

    assert machine.banner == "alpaca_disconnected"
    assert machine.screen == ScreenState.TRADE_WAKE


def test_mismatched_clear_event_does_not_clear_banner():
    machine = StateMachine()
    machine = machine.advance([_event("alpaca_disconnected")], now=_NOW)
    machine = machine.advance([_event("wifi_connected")], now=_NOW)

    assert machine.banner == "alpaca_disconnected"


def test_update_available_and_applied_set_and_clear_banner():
    machine = StateMachine()
    machine = machine.advance([_event("update_available")], now=_NOW)
    assert machine.banner == "update_available"

    machine = machine.advance([_event("update_applied")], now=_NOW)
    assert machine.banner is None


def test_notification_event_sets_transient_notification():
    machine = StateMachine()
    machine = machine.advance([_event("notification", {"message": "New bot available: Draco v2"})], now=_NOW)

    assert machine.notification == "New bot available: Draco v2"
    assert machine.notification_until == _NOW + timedelta(seconds=NOTIFICATION_DURATION_SECONDS)
    assert machine.screen == ScreenState.IDLE  # notifications don't change the screen


def test_notification_falls_back_to_banner_payload_key():
    machine = StateMachine()
    machine = machine.advance([_event("notification", {"banner": "update required"})], now=_NOW)

    assert machine.notification == "update required"


def test_notification_auto_expires():
    machine = StateMachine()
    machine = machine.advance([_event("notification", {"message": "new bot"})], now=_NOW)
    assert machine.notification is not None

    later = _NOW + timedelta(seconds=NOTIFICATION_DURATION_SECONDS + 1)
    machine = machine.advance([], now=later)

    assert machine.notification is None
    assert machine.notification_until is None


def test_top_banner_prefers_connection_banner_over_notification():
    machine = StateMachine()
    machine = machine.advance(
        [_event("wifi_disconnected"), _event("notification", {"message": "new bot"})], now=_NOW
    )

    assert machine.banner == "wifi_disconnected"
    assert machine.notification == "new bot"
    assert machine.top_banner == "wifi_disconnected"


def test_top_banner_falls_back_to_notification_when_no_connection_banner():
    machine = StateMachine()
    machine = machine.advance([_event("notification", {"message": "new bot"})], now=_NOW)

    assert machine.top_banner == "new bot"


def test_wifi_onboarding_started_switches_to_wifi_setup_screen():
    machine = StateMachine()
    machine = machine.advance(
        [_event("wifi_onboarding_started", {"ap_ssid": "MonstraPro-AB12", "setup_url": "http://setup.monstra"})],
        now=_NOW,
    )

    assert machine.screen == ScreenState.WIFI_SETUP
    assert machine.ap_ssid == "MonstraPro-AB12"
    assert machine.setup_url == "http://setup.monstra"


def test_wifi_connected_returns_to_idle_from_wifi_setup():
    machine = StateMachine(screen=ScreenState.WIFI_SETUP, ap_ssid="MonstraPro-AB12", setup_url="http://setup.monstra")
    machine = machine.advance([_event("wifi_connected", {"ssid": "HomeNetwork"})], now=_NOW)

    assert machine.screen == ScreenState.IDLE
    # ap_ssid/setup_url are stale but harmless once off the wifi_setup screen


def test_wifi_connected_also_clears_wifi_disconnected_banner_from_wifi_setup():
    machine = StateMachine(screen=ScreenState.WIFI_SETUP, banner="wifi_disconnected")
    machine = machine.advance([_event("wifi_connected")], now=_NOW)

    assert machine.screen == ScreenState.IDLE
    assert machine.banner is None


def test_wifi_connected_outside_wifi_setup_does_not_change_screen():
    machine = StateMachine(screen=ScreenState.AWAITING_ACTIVATION, device_serial="MPB-ABC123")
    machine = machine.advance([_event("wifi_connected")], now=_NOW)

    assert machine.screen == ScreenState.AWAITING_ACTIVATION


def test_awaiting_activation_supersedes_wifi_setup():
    """Simulates the real handoff: device_agent gets the box online (wifi_setup
    -> idle), then trading_worker's own poll loop publishes awaiting_activation
    shortly after - display.state doesn't need to know about pairing codes."""
    machine = StateMachine()
    machine = machine.advance(
        [_event("wifi_onboarding_started", {"ap_ssid": "MonstraPro-AB12", "setup_url": "http://setup.monstra"})],
        now=_NOW,
    )
    machine = machine.advance([_event("wifi_connected")], now=_NOW)
    assert machine.screen == ScreenState.IDLE

    machine = machine.advance([_event("awaiting_activation", {"device_serial": "MPB-ABC123"})], now=_NOW)

    assert machine.screen == ScreenState.AWAITING_ACTIVATION
    assert machine.device_serial == "MPB-ABC123"
