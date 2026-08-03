"""Regression guard for a real bug found on physical Pi 5 hardware:
main() used to unconditionally construct+start SetupServer (binding port
80) before ever checking whether onboarding was actually needed. When
has_usable_connection() was momentarily false at some earlier boot/restart,
device_agent got stuck in AP mode holding port 80 indefinitely - even
though the device genuinely had working Wi-Fi - permanently blocking
monstrapro-portfolio-web.service (which also binds port 80) from ever
starting. See device_agent.main's inline comment."""

from __future__ import annotations

import device_agent.main as main_module
from device_agent.network import SimulatedNetworkManager


class _ExplodingSetupServer:
    """Stands in for SetupServer - construction alone means main() tried to
    bind port 80, which the "already connected" path must never do."""

    def __init__(self, *args, **kwargs) -> None:
        raise AssertionError("SetupServer must not be constructed when already connected")


def test_main_skips_setup_server_entirely_when_already_connected(monkeypatch, tmp_path):
    monkeypatch.setenv("MONSTRAPRO_DATA_DIR", str(tmp_path))
    monkeypatch.setattr(
        main_module, "_build_network_manager", lambda: SimulatedNetworkManager(initially_connected=True)
    )
    monkeypatch.setattr(main_module, "SetupServer", _ExplodingSetupServer)

    main_module.main()  # must return cleanly without ever touching SetupServer
