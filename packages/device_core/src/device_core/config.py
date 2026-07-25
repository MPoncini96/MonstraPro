"""Layered configuration loader.

Layers, lowest to highest precedence (see ARCHITECTURE.md section 6):

    1. code defaults
    2. config TOML file (device-level, non-secret settings)
    3. environment variables (dev-only overrides)

ARCHITECTURE.md's third layer ("SQLite device/settings rows") is
deliberately NOT merged in here: activation state and strategy
configuration are dynamic, DB-backed concerns exposed through
``device_core.device.Device`` and ``Database.get_active_strategy_configs``,
not through this static Config object, since they require a live DB
connection this module doesn't own.

Secrets (Alpaca credentials) are never read from the TOML layer - only
from the encrypted alpaca_credentials table via Database + crypto.py.
"""

from __future__ import annotations

import os
import platform
import tomllib
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any


def _default_data_dir() -> Path:
    if platform.system() == "Linux":
        return Path("/var/lib/monstrapro")
    return Path("./.data").resolve()


def _default_config_toml_path() -> Path:
    override = os.environ.get("MONSTRAPRO_CONFIG_FILE")
    if override:
        return Path(override)
    if platform.system() == "Linux":
        return Path("/etc/monstrapro/config.toml")
    return Path("./config.toml").resolve()


@dataclass(frozen=True)
class Config:
    data_dir: Path
    monstra_pro_base_url: str = "https://monstra.pro"
    log_level: str = "INFO"
    poll_interval_seconds: int = 30

    @property
    def db_path(self) -> Path:
        return self.data_dir / "monstrapro.db"

    @property
    def device_key_path(self) -> Path:
        return self.data_dir / "device.key"


def _load_toml(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    with path.open("rb") as fh:
        return tomllib.load(fh)


def _load_env() -> dict[str, Any]:
    values: dict[str, Any] = {}
    if "MONSTRA_PRO_BASE_URL" in os.environ:
        values["monstra_pro_base_url"] = os.environ["MONSTRA_PRO_BASE_URL"]
    if "MONSTRAPRO_DATA_DIR" in os.environ:
        values["data_dir"] = os.environ["MONSTRAPRO_DATA_DIR"]
    if "MONSTRAPRO_LOG_LEVEL" in os.environ:
        values["log_level"] = os.environ["MONSTRAPRO_LOG_LEVEL"]
    if "MONSTRAPRO_POLL_INTERVAL_SECONDS" in os.environ:
        values["poll_interval_seconds"] = int(os.environ["MONSTRAPRO_POLL_INTERVAL_SECONDS"])
    return values


def load_config(overrides: Mapping[str, Any] | None = None) -> Config:
    """Build a Config by merging defaults -> TOML file -> env vars -> overrides.

    ``overrides`` is mainly for tests and for services that need to force a
    specific data_dir; production code should rely on the TOML file + env
    layers instead of passing overrides.
    """
    values: dict[str, Any] = {"data_dir": _default_data_dir()}
    values.update(_load_toml(_default_config_toml_path()))
    values.update(_load_env())
    if overrides:
        values.update(overrides)

    data_dir = Path(values["data_dir"]).expanduser().resolve()
    config = Config(
        data_dir=data_dir,
        monstra_pro_base_url=str(values.get("monstra_pro_base_url", Config.monstra_pro_base_url)),
        log_level=str(values.get("log_level", Config.log_level)).upper(),
        poll_interval_seconds=int(values.get("poll_interval_seconds", Config.poll_interval_seconds)),
    )
    config.data_dir.mkdir(parents=True, exist_ok=True)
    return config
