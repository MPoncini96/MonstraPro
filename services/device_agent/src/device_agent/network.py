"""Injectable interfaces over NetworkManager - the hardware/OS boundary
ARCHITECTURE.md section 1 calls for, same pattern as display/renderer.py's
Renderer protocol. `onboarding.py` only ever depends on these Protocols, so
it can be fully unit-tested without touching a real network stack -
required by this project's own rules (never run NetworkManager/access-point
commands on a Windows dev machine).

`NetworkManagerClient` is the real implementation, shelling out to `nmcli`
(present by default on Raspberry Pi OS). It is only ever instantiated on
Linux (see main.py's `_build_network_manager`) - nothing in this module's
import path touches `subprocess` at import time, so importing this module on
Windows is always safe.

`SimulatedNetworkManager` is an in-memory stand-in for local development and
tests: it never shells out to anything, records every call it receives, and
lets tests script exactly which SSIDs are "in range" and which submitted
passwords should fail to join - deterministic behavior a real Wi-Fi radio
can't offer in a test suite.
"""

from __future__ import annotations

import subprocess
from dataclasses import dataclass, field
from typing import Protocol


@dataclass(frozen=True)
class WifiNetwork:
    ssid: str
    signal: int  # 0-100
    secured: bool


class ConnectivityChecker(Protocol):
    def has_usable_connection(self) -> bool: ...


class AccessPointController(Protocol):
    def start(self, ssid: str) -> None: ...
    def stop(self) -> None: ...


class WifiScanner(Protocol):
    def scan(self) -> list[WifiNetwork]: ...


class WifiConnector(Protocol):
    def connect_and_save(self, ssid: str, password: str | None) -> bool: ...


class NetworkManagerClient:
    """Real ConnectivityChecker + AccessPointController + WifiScanner +
    WifiConnector, driven entirely through `nmcli`. `nmcli -t` (terse) output
    is colon-delimited per NetworkManager's own escaping rules; this is a
    foundation-level parser (handles the common case) and is not exercised
    by the test suite - see image/README.md "what remains" for real-hardware
    validation of nmcli's exact output on Raspberry Pi OS's shipped
    NetworkManager version.
    """

    HOTSPOT_CONNECTION_NAME = "monstrapro-setup-ap"

    def __init__(self, *, ap_interface: str = "wlan0", timeout: float = 30.0) -> None:
        self._ap_interface = ap_interface
        self._timeout = timeout

    def _run(self, args: list[str]) -> subprocess.CompletedProcess:
        return subprocess.run(
            ["nmcli", *args], capture_output=True, text=True, timeout=self._timeout, check=False
        )

    def has_usable_connection(self) -> bool:
        result = self._run(["-t", "-f", "TYPE,STATE", "device"])
        if result.returncode != 0:
            return False
        for line in result.stdout.strip().splitlines():
            parts = line.split(":")
            if len(parts) >= 2 and parts[0] == "wifi" and parts[1] == "connected":
                return True
        return False

    def scan(self) -> list[WifiNetwork]:
        self._run(["device", "wifi", "rescan"])
        result = self._run(["-t", "-f", "SSID,SIGNAL,SECURITY", "device", "wifi", "list"])
        if result.returncode != 0:
            return []
        networks: list[WifiNetwork] = []
        seen: set[str] = set()
        for line in result.stdout.strip().splitlines():
            parts = line.split(":")
            if len(parts) < 3 or not parts[0] or parts[0] in seen:
                continue
            seen.add(parts[0])
            try:
                signal = int(parts[1])
            except ValueError:
                signal = 0
            networks.append(WifiNetwork(ssid=parts[0], signal=signal, secured=parts[2] not in ("", "--")))
        return sorted(networks, key=lambda n: n.signal, reverse=True)

    def start(self, ssid: str) -> None:
        self._run(
            [
                "device", "wifi", "hotspot",
                "ifname", self._ap_interface,
                "con-name", self.HOTSPOT_CONNECTION_NAME,
                "ssid", ssid,
            ]
        )

    def stop(self) -> None:
        self._run(["connection", "down", self.HOTSPOT_CONNECTION_NAME])
        self._run(["connection", "delete", self.HOTSPOT_CONNECTION_NAME])

    def connect_and_save(self, ssid: str, password: str | None) -> bool:
        args = ["device", "wifi", "connect", ssid]
        if password:
            args += ["password", password]
        return self._run(args).returncode == 0


@dataclass
class SimulatedNetworkManager:
    """In-memory ConnectivityChecker + AccessPointController + WifiScanner +
    WifiConnector for local dev/tests - never touches the host's real
    networking, safe to use on Windows.

        network = SimulatedNetworkManager(
            available_networks=[WifiNetwork("HomeWifi", 80, True)],
            fail_ssids={"WrongPassword"},
        )
    """

    initially_connected: bool = False
    available_networks: list[WifiNetwork] = field(default_factory=list)
    fail_ssids: frozenset[str] = frozenset()

    ap_active: bool = field(default=False, init=False)
    ap_ssid: str | None = field(default=None, init=False)
    joined_ssid: str | None = field(default=None, init=False)
    saved_connections: list[str] = field(default_factory=list, init=False)
    calls: list[str] = field(default_factory=list, init=False)

    def has_usable_connection(self) -> bool:
        self.calls.append("has_usable_connection")
        return self.joined_ssid is not None or self.initially_connected

    def scan(self) -> list[WifiNetwork]:
        self.calls.append("scan")
        return list(self.available_networks)

    def start(self, ssid: str) -> None:
        self.calls.append(f"start:{ssid}")
        self.ap_active = True
        self.ap_ssid = ssid

    def stop(self) -> None:
        self.calls.append("stop")
        self.ap_active = False

    def connect_and_save(self, ssid: str, password: str | None) -> bool:
        self.calls.append(f"connect:{ssid}")
        if ssid in self.fail_ssids:
            return False
        self.joined_ssid = ssid
        self.saved_connections.append(ssid)
        return True
