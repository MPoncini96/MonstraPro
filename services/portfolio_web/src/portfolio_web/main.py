"""portfolio_web entrypoint - systemd target monstrapro-portfolio-web.service.

Always-on local page (see server.py's docstring for how this differs from
device_agent's temporary first-boot setup page) that lets the owner toggle
bots on/off and manage locked individual-stock holdings from a browser on
the same home network. PIN-gated - see auth.py. The PIN itself lives on
device_core's `device` row and is shown on the LCD by services/display;
this process only ensures one exists (idempotent) so it's never blank the
first time someone looks at the screen.
"""

from __future__ import annotations

import logging
import time

from device_core.core import DeviceCore

from portfolio_web.auth import SessionStore
from portfolio_web.server import PortfolioServer

logger = logging.getLogger(__name__)

PORTFOLIO_SERVER_PORT = 80
IDLE_SLEEP_SECONDS = 3600


def main() -> None:
    core = DeviceCore.load()
    core.devices.get_or_create_local_pin()

    sessions = SessionStore()
    server = PortfolioServer(core, sessions, port=PORTFOLIO_SERVER_PORT)
    server.start()
    logger.info("portfolio_web listening on port %s", PORTFOLIO_SERVER_PORT)

    try:
        while True:
            time.sleep(IDLE_SLEEP_SECONDS)
    finally:
        server.stop()


if __name__ == "__main__":
    main()
