"""device_agent entrypoint - systemd target monstrapro-agent.service.

First-boot Wi-Fi onboarding (Objectives.txt, image/README.md). If the
device already has a usable saved connection, `run_onboarding` is a fast
no-op and this process just idles/exits (see image/systemd/
monstrapro-agent.service: Type=simple + Restart=on-failure, so a clean exit
after "already_connected" is expected steady state, not a crash-loop).
Otherwise it stands up a temporary access point + local setup page, waits
for the customer to submit Wi-Fi credentials, saves them via
NetworkManager, and hands off - trading_worker's own `awaiting_activation`
flow (activation.py) takes it from there once the device can reach
monstra.pro; this module knows nothing about activation or pairing codes.

Real NetworkManager/hotspot/setup-page I/O only happens through
device_agent.network.NetworkManagerClient. `main()` is the only place that
decides whether to use it (Linux) or SimulatedNetworkManager (anything
else, or DEVICE_AGENT_SIMULATE=1 for local testing on real Linux hardware
without touching its Wi-Fi) - same pattern trading_worker/updater use for
their own injectable I/O boundaries.
"""

from __future__ import annotations

import logging
import os
import platform

from device_core.core import DeviceCore

from device_agent.network import NetworkManagerClient, SimulatedNetworkManager
from device_agent.onboarding import run_onboarding
from device_agent.setup_server import SetupServer

logger = logging.getLogger(__name__)

SETUP_SERVER_PORT = 80


def _build_network_manager():
    if platform.system() == "Linux" and os.environ.get("DEVICE_AGENT_SIMULATE") != "1":
        return NetworkManagerClient()
    logger.warning("using SimulatedNetworkManager (non-Linux host or DEVICE_AGENT_SIMULATE=1)")
    return SimulatedNetworkManager()


def main() -> None:
    core = DeviceCore.load()
    device = core.devices.get_or_create()
    network = _build_network_manager()

    setup_server = SetupServer(network, port=SETUP_SERVER_PORT)
    setup_server.start()
    try:
        result = run_onboarding(
            core,
            connectivity=network,
            access_point=network,
            connector=network,
            submissions=setup_server,
            device_serial=device.serial,
        )
        logger.info("device_agent onboarding finished: %s", result)
    finally:
        setup_server.stop()


if __name__ == "__main__":
    main()
