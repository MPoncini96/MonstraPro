"""Shared appliance infrastructure: config, database, crypto, logging,
local eventing.

Trading-agnostic on purpose - none of this package knows what a "bot" is.
See ARCHITECTURE.md sections 6-9.

    from device_core import Config, Database, Device, EventBus, EventType, load_config

    config = load_config()
    db = Database(config)
    device = Device.load(db)
    events = EventBus(db)
"""

from device_core.config import Config, load_config
from device_core.db.database import Database
from device_core.device import Device
from device_core.events import EventBus, EventType

__all__ = ["Config", "load_config", "Database", "Device", "EventBus", "EventType"]
