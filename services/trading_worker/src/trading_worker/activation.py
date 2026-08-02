"""Activation state machine: is this device allowed to trade yet?

ARCHITECTURE.md section 4.1 describes trading_worker polling a monstra.pro
device-status endpoint before entering trading mode - that endpoint doesn't
exist yet (it's Track B / website work). `ActivationClient` is the seam:
`LocalActivationClient` answers the question from the local DB alone, no
network call, so trading_worker is structurally complete now and swapping
in a real `HTTPActivationClient` later (once monstra.pro's device-status
endpoint exists) is a one-file change — nothing in loop.py/main.py needs to
change, they only depend on the `ActivationClient` protocol.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from device_core.core import DeviceCore


@dataclass(frozen=True)
class ActivationStatus:
    activated: bool
    owner_ref: str | None = None
    device_serial: str | None = None


class ActivationClient(Protocol):
    def check_status(self) -> ActivationStatus: ...


class LocalActivationClient:
    """Reads `device.activated_at` straight from the local DB.

    Note: there's no plaintext activation/pairing code surfaced here —
    `device.activation_code_hash` stores only a hash, and nothing in
    device_core generates or persists the plaintext code yet (that belongs
    to a not-yet-built provisioning flow). `display` shows `device_serial`
    while awaiting activation for now.
    """

    def __init__(self, core: DeviceCore) -> None:
        self._core = core

    def check_status(self) -> ActivationStatus:
        device = self._core.devices.get_or_create()
        return ActivationStatus(
            activated=device.is_activated,
            owner_ref=device.owner_ref,
            device_serial=device.serial,
        )
