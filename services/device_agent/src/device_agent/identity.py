"""Derives a stable, unique access-point SSID from device identity.

Objectives.txt asks for `MonstraPro-XXXX`, "using a unique suffix derived
from the device identity" - device_core.repositories.device already
generates a stable serial per device (`device.serial`, e.g.
"MPB-AB12CD34EF56"). The AP suffix here is a short hash of that serial, not
the serial itself, so the temporary access point broadcast over the air
doesn't leak the full device serial to anyone in Wi-Fi range. Deterministic
and stable across reboots without needing any extra stored state.
"""

from __future__ import annotations

import hashlib

AP_SSID_PREFIX = "MonstraPro-"


def ap_suffix_for(device_serial: str) -> str:
    """4 uppercase hex characters, deterministic per device_serial."""
    digest = hashlib.sha256(device_serial.encode("utf-8")).hexdigest()
    return digest[:4].upper()


def ap_ssid_for(device_serial: str) -> str:
    return f"{AP_SSID_PREFIX}{ap_suffix_for(device_serial)}"
