"""Polls monstra.pro for an owner-initiated "run now" request and
acknowledges it once acted on (or discarded). See NextJS_Monsta's
POST /api/devices/[deviceId]/run-now (sets it, owner's browser only,
market-hours gated there too), GET /api/devices/run-request (this module's
poll), and POST /api/devices/run-request/ack (this module's ack).
"""

from __future__ import annotations

import logging
from typing import Any

import requests

from device_core.core import DeviceCore

logger = logging.getLogger(__name__)


def check_run_requested(core: DeviceCore, *, timeout_seconds: float = 10.0, session: Any = None) -> bool:
    """Returns True if the owner has asked, via monstra.pro, for an
    immediate trading cycle outside the normal schedule. Every network
    failure is treated as "no request pending" rather than raised, matching
    this module's siblings' (activation.py, alpaca_sync.py) resilience
    philosophy - a transient connectivity blip should never itself trigger
    (or block) a trading cycle.
    """
    token = core.devices.get_device_token()
    if token is None:
        return False

    http = session if session is not None else requests
    try:
        response = http.get(
            f"{core.config.monstra_pro_api_url}/api/devices/run-request",
            headers={"Authorization": f"Bearer {token}"},
            timeout=timeout_seconds,
        )
        response.raise_for_status()
        body = response.json()
    except Exception:
        logger.warning("run-request poll to monstra.pro failed; skipping", exc_info=True)
        return False

    return bool(body.get("requested"))


def ack_run_request(core: DeviceCore, *, timeout_seconds: float = 10.0, session: Any = None) -> None:
    """Clears the pending run-now request once this device has acted on it
    (or decided not to - e.g. the market closed in the gap since it was
    requested). Best-effort: if this fails, the next poll simply sees
    `requested: True` again and the device just runs an extra cycle - safe,
    if a little redundant - so failures here are logged and swallowed
    rather than raised.
    """
    token = core.devices.get_device_token()
    if token is None:
        return

    http = session if session is not None else requests
    try:
        response = http.post(
            f"{core.config.monstra_pro_api_url}/api/devices/run-request/ack",
            headers={"Authorization": f"Bearer {token}"},
            timeout=timeout_seconds,
        )
        response.raise_for_status()
    except Exception:
        logger.warning("run-request ack to monstra.pro failed; next poll may see a stale request", exc_info=True)
