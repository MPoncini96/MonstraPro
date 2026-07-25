"""Shared appliance infrastructure: config, database, crypto, logging,
local eventing.

Trading-agnostic on purpose - none of this package knows what a "bot" is.
See ARCHITECTURE.md sections 6-9.

    from device_core import DeviceCore, EventType

    core = DeviceCore.load()
    device = core.devices.get_or_create()
    core.credentials.save(mode="paper", api_key=..., api_secret=..., base_url=...)
    core.signals.store(bot_id="alpha1", bot_type="alpha1", signal="buy", payload={...})
    core.events.publish(EventType.TRADE_EXECUTED, {"bot_slug": "alpha1"})
"""

from device_core.config import Config, ConfigError, load_config
from device_core.core import DeviceCore
from device_core.events import EventType

__all__ = ["DeviceCore", "EventType", "Config", "ConfigError", "load_config"]
