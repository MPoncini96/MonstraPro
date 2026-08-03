"""Activation state machine: is this device allowed to trade yet?

ARCHITECTURE.md section 4.1 describes trading_worker polling a monstra.pro
device-status endpoint before entering trading mode. That endpoint now
exists for real (NextJS_Monsta's /api/devices/register, /api/devices/pair,
/api/devices/status - see HTTPActivationClient below, which is the
"swap in a real HTTPActivationClient later" this docstring used to promise).
`ActivationClient` is the seam that made that swap a one-file change:
nothing in loop.py/main.py needs to change, they only depend on the
`ActivationClient` protocol. `LocalActivationClient` (local DB only, no
network) still exists deliberately - offline/simulated dev and tests use
it, matching device_agent.main._build_network_manager's identical
Linux-real/non-Linux-simulated split.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Protocol

import requests

from device_core.core import DeviceCore
from device_core.repositories.device import Device

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class ActivationStatus:
    activated: bool
    owner_ref: str | None = None
    device_serial: str | None = None
    # Only ever set while NOT activated - the code the owner needs to type
    # into monstra.pro's /dashboard/devices/pair. None for
    # LocalActivationClient (which never registers with monstra.pro at all)
    # and for HTTPActivationClient before its first successful registration.
    pairing_code: str | None = None


class ActivationClient(Protocol):
    def check_status(self) -> ActivationStatus: ...


class LocalActivationClient:
    """Reads `device.activated_at` straight from the local DB - never talks
    to monstra.pro at all. Used for offline/simulated dev and tests; the
    real device uses HTTPActivationClient instead (see main.py's
    _build_activation_client, mirroring device_agent's identical
    Linux-real/non-Linux-simulated split)."""

    def __init__(self, core: DeviceCore) -> None:
        self._core = core

    def check_status(self) -> ActivationStatus:
        device = self._core.devices.get_or_create()
        return ActivationStatus(
            activated=device.is_activated,
            owner_ref=device.owner_ref,
            device_serial=device.serial,
        )


class HTTPActivationClient:
    """Talks to monstra.pro's device API for real:
    POST /api/devices/register (once - or again if the last pairing code
    expired unused) to get a bearer token + pairing code, then
    GET /api/devices/status (bearer-authenticated) until the owner has
    paired the device via monstra.pro's /dashboard/devices/pair. See
    NextJS_Monsta's src/app/api/devices/{register,pair,status}/route.ts for
    the server side of this same protocol.

    Every network failure (registration or polling) is treated as "not
    activated yet, try again next poll" rather than raised - this module's
    existing philosophy (see main._wait_for_activation) is that "waiting" is
    always a safe fallback state, never a reason to crash trading_worker
    over a transient connectivity blip.
    """

    # Written locally as owner_ref once activation is confirmed.
    # /api/devices/status deliberately only ever returns booleans
    # (`activated`, `ownerLinked`), never an actual owner identifier - real
    # ownership lives entirely on the monstra.pro side. This is just a
    # local marker satisfying DeviceRepository.activate()'s existing
    # owner_ref contract, not a real per-customer reference.
    OWNER_REF = "monstra.pro"

    def __init__(self, core: DeviceCore, *, timeout_seconds: float = 10.0, session: Any = None) -> None:
        self._core = core
        self._timeout_seconds = timeout_seconds
        self._session = session if session is not None else requests

    def check_status(self) -> ActivationStatus:
        device = self._core.devices.get_or_create()
        if device.is_activated:
            return ActivationStatus(activated=True, owner_ref=device.owner_ref, device_serial=device.serial)

        if not device.has_device_token or device.pairing_code_expired:
            registered = self._register(device)
            if registered is not None:
                device = registered

        if not device.has_device_token:
            # Registration never succeeded (network down, monstra.pro
            # unreachable, ...) - nothing to poll with yet.
            return ActivationStatus(activated=False, device_serial=device.serial, pairing_code=device.pairing_code)

        return self._poll(device)

    def _register(self, device: Device) -> Device | None:
        try:
            response = self._session.post(
                f"{self._core.config.monstra_pro_api_url}/api/devices/register",
                json={"serial": device.serial},
                timeout=self._timeout_seconds,
            )
            response.raise_for_status()
            body = response.json()
            pairing_code_expires_at = datetime.fromisoformat(
                body["pairingCodeExpiresAt"].replace("Z", "+00:00")
            )
            return self._core.devices.store_registration(
                device_token=body["deviceToken"],
                pairing_code=body["pairingCode"],
                pairing_code_expires_at=pairing_code_expires_at,
            )
        except Exception:
            logger.warning("device registration with monstra.pro failed; will retry next poll", exc_info=True)
            return None

    def _poll(self, device: Device) -> ActivationStatus:
        token = self._core.devices.get_device_token()
        if token is None:
            return ActivationStatus(activated=False, device_serial=device.serial, pairing_code=device.pairing_code)

        try:
            response = self._session.get(
                f"{self._core.config.monstra_pro_api_url}/api/devices/status",
                headers={"Authorization": f"Bearer {token}"},
                timeout=self._timeout_seconds,
            )
            response.raise_for_status()
            body = response.json()
        except Exception:
            logger.warning("device status poll to monstra.pro failed; will retry", exc_info=True)
            return ActivationStatus(activated=False, device_serial=device.serial, pairing_code=device.pairing_code)

        if not body.get("activated"):
            return ActivationStatus(activated=False, device_serial=device.serial, pairing_code=device.pairing_code)

        activated = self._core.devices.activate(owner_ref=self.OWNER_REF)
        return ActivationStatus(activated=True, owner_ref=activated.owner_ref, device_serial=activated.serial)
