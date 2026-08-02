"""First-boot Wi-Fi onboarding orchestrator (image/README.md, Objectives.txt).

`run_onboarding` implements the whole flow as one injectable, unit-testable
function - every I/O edge (connectivity check, AP start/stop, network scan,
join+save, waiting for the customer's submission, sleeping between polls) is
a constructor/parameter seam, same pattern as updater.main.run_once:

  1. connectivity.has_usable_connection() -> True: nothing to do, return.
  2. Otherwise start a temporary AP named via identity.ap_ssid_for(), derived
     from the device serial (never the serial itself, so it isn't broadcast
     over the air).
  3. Publish `wifi_onboarding_started` so `display` shows the AP name + setup
     URL (display/state.py's WIFI_SETUP screen): "Connect your phone to
     <ap_ssid> / Then visit <setup_url>".
  4. Poll `submissions` (backed by setup_server.SetupServer's local HTTP
     page) until the customer submits a network + password.
  5. connector.connect_and_save() - the password only ever reaches the
     device's own NetworkManager. It is never logged, never persisted by
     this package, and never sent to any Monstra server - see
     image/README.md "local-credentials architecture".
  6. On success: stop the AP, publish `wifi_connected`, return. On failure:
     stay in AP mode and keep polling - the customer can retry from the
     setup page.

This module intentionally knows nothing about device activation or pairing
codes. Getting the device online is its only job; trading_worker's existing
`awaiting_activation` polling (activation.py) picks up on its own once the
device can reach monstra.pro, and display/state.py's WIFI_SETUP -> idle ->
awaiting_activation sequence is what actually satisfies "transition the
display to device registration and pairing-code status."
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass
from typing import Callable, Protocol

from device_core.core import DeviceCore
from device_core.events import EventType

from device_agent.identity import ap_ssid_for
from device_agent.network import AccessPointController, ConnectivityChecker, WifiConnector

logger = logging.getLogger(__name__)

SETUP_URL = "http://setup.monstra"
DEFAULT_POLL_INTERVAL_SECONDS = 2.0


@dataclass(frozen=True)
class SubmittedCredentials:
    ssid: str
    password: str | None


class SetupSubmissionSource(Protocol):
    def poll(self) -> SubmittedCredentials | None:
        """Non-blocking: return the customer's submitted network+password
        once posted to the setup page, else None. The caller (this module)
        drives the wait loop so it stays interruptible and testable."""
        ...


def run_onboarding(
    core: DeviceCore,
    *,
    connectivity: ConnectivityChecker,
    access_point: AccessPointController,
    connector: WifiConnector,
    submissions: SetupSubmissionSource,
    device_serial: str,
    sleep: Callable[[float], None] = time.sleep,
    poll_interval_seconds: float = DEFAULT_POLL_INTERVAL_SECONDS,
    max_polls: int | None = None,
) -> str:
    """Returns "already_connected", "connected", or "gave_up" (only
    reachable when `max_polls` is set - production callers leave it None and
    loop until connected; tests use it to bound the loop deterministically).
    """
    if connectivity.has_usable_connection():
        logger.info("usable Wi-Fi connection already present; skipping onboarding")
        return "already_connected"

    ssid = ap_ssid_for(device_serial)
    access_point.start(ssid)
    core.events.publish(EventType.WIFI_ONBOARDING_STARTED, {"ap_ssid": ssid, "setup_url": SETUP_URL})
    logger.info("started onboarding access point ssid=%s", ssid)

    try:
        polls = 0
        while True:
            submission = submissions.poll()
            if submission is not None:
                if connector.connect_and_save(submission.ssid, submission.password):
                    core.events.publish(EventType.WIFI_CONNECTED, {"ssid": submission.ssid})
                    logger.info("joined Wi-Fi network ssid=%s", submission.ssid)
                    return "connected"
                logger.warning("failed to join submitted Wi-Fi network ssid=%s; staying in AP mode", submission.ssid)

            polls += 1
            if max_polls is not None and polls >= max_polls:
                return "gave_up"
            sleep(poll_interval_seconds)
    finally:
        access_point.stop()
