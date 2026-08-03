"""Syncs Alpaca credentials from monstra.pro into the device's own local
Vault - the one remaining piece of Objectives.txt's "User sends data from
Monstra.pro to their MonstraProBox, including alpaca key and secret" that
had never actually been built: device_core.repositories.credentials.
CredentialRepository.save() was, until this module, only ever called from
tests, in either repo. See NextJS_Monsta's
GET /api/devices/alpaca-credentials for the server side of this exact
protocol - the one device endpoint that returns raw credentials at all
(everywhere else, e.g. /api/devices/strategy-config, only ever reports
connection status, never the secret).
"""

from __future__ import annotations

import logging
from typing import Any

import requests

from device_core.core import DeviceCore

logger = logging.getLogger(__name__)


def sync_alpaca_credentials_if_missing(
    core: DeviceCore,
    *,
    timeout_seconds: float = 10.0,
    session: Any = None,
) -> bool:
    """Returns True if local Alpaca credentials exist by the time this
    returns - either already did, or were freshly synced this call.

    Only ever calls monstra.pro when NO local credentials exist yet for
    either mode - once synced, the device relies on its own local copy from
    then on and never touches the network for this again, same "durable
    once known" philosophy as HTTPActivationClient's local-activation
    short-circuit (see activation.py). Reconnecting or rotating the Alpaca
    connection from monstra.pro after this point is not picked up
    automatically - a real gap, not something this call tries to solve;
    flagged here rather than silently guessed at.

    Every network failure is treated as "not synced yet, try again next
    call" rather than raised, matching this module's sibling
    HTTPActivationClient's existing resilience philosophy.
    """
    if core.credentials.get("live") or core.credentials.get("paper"):
        return True

    token = core.devices.get_device_token()
    if token is None:
        return False

    http = session if session is not None else requests
    try:
        response = http.get(
            f"{core.config.monstra_pro_api_url}/api/devices/alpaca-credentials",
            headers={"Authorization": f"Bearer {token}"},
            timeout=timeout_seconds,
        )
        response.raise_for_status()
        body = response.json()
    except Exception:
        logger.warning("Alpaca credential sync with monstra.pro failed; will retry", exc_info=True)
        return False

    if not body.get("connected"):
        return False

    core.credentials.save(
        mode=body["mode"],
        api_key=body["apiKey"],
        api_secret=body["secretKey"],
        base_url=body["baseUrl"],
    )
    logger.info("synced Alpaca credentials from monstra.pro (mode=%s)", body["mode"])
    return True
