"""Event type and severity constants for the device_event queue.

The queue implementation (publish/list_unconsumed/mark_consumed) lives in
device_core.repositories.device_event.DeviceEventRepository - this module
is just the shared vocabulary so publishers and consumers agree on type
strings without hardcoding them.
"""

from __future__ import annotations

from enum import StrEnum


class EventType(StrEnum):
    DEVICE_PROVISIONED = "device_provisioned"
    DEVICE_ACTIVATED = "device_activated"
    WIFI_CONNECTED = "wifi_connected"
    WIFI_DISCONNECTED = "wifi_disconnected"
    ALPACA_CONNECTED = "alpaca_connected"
    ALPACA_DISCONNECTED = "alpaca_disconnected"
    SIGNAL_GENERATED = "signal_generated"
    TRADE_EXECUTED = "trade_executed"
    UPDATE_AVAILABLE = "update_available"
    UPDATE_APPLIED = "update_applied"
    FATAL_ERROR = "fatal_error"


VALID_SEVERITIES = frozenset({"info", "warning", "error", "critical"})
