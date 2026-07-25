"""Typed configuration loader.

Precedence, lowest to highest:

    1. code defaults
    2. /etc/monstrapro/config.toml (path overridable via
       MONSTRAPRO_CONFIG_FILE, used by tests/dev so nothing touches /etc)
    3. a fixed whitelist of environment variables (dev overrides)
    4. an explicit ``overrides`` dict passed to load_config() (tests only)

Alpaca credentials are never a config concern: the env whitelist below has
no credential-shaped entries (so it's structurally impossible to pick one
up), and the TOML layer is actively scanned and rejected if it contains
anything alpaca/credential/secret-shaped - see _reject_credential_keys.
Credentials live only in the encrypted alpaca_credentials table, reached
through DeviceCore.credentials / vault.py.
"""

from __future__ import annotations

import os
import platform
import tomllib
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

_VALID_LOG_LEVELS = {"DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"}
_FORBIDDEN_TOML_KEY_MARKERS = ("alpaca", "credential", "api_key", "api_secret")


class ConfigError(Exception):
    """Raised for missing/invalid configuration - always with a clear reason."""


@dataclass(frozen=True)
class Config:
    data_dir: Path
    sqlite_url: str
    encryption_key_path: Path
    log_level: str
    monstra_pro_api_url: str
    event_poll_interval_seconds: int
    release_dir: Path


def _default_data_dir() -> Path:
    if platform.system() == "Linux":
        return Path("/var/lib/monstrapro")
    return Path("./.data").resolve()


def _default_config_toml_path() -> Path:
    override = os.environ.get("MONSTRAPRO_CONFIG_FILE")
    if override:
        return Path(override)
    return Path("/etc/monstrapro/config.toml")


def _reject_credential_keys(values: Mapping[str, Any], *, source: str) -> None:
    for key in values:
        lowered = key.lower()
        if any(marker in lowered for marker in _FORBIDDEN_TOML_KEY_MARKERS):
            raise ConfigError(
                f"{source} must not set {key!r} - Alpaca credentials are never loaded "
                "from config files or environment variables; use "
                "DeviceCore.credentials.save() instead."
            )


def _load_toml(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    with path.open("rb") as fh:
        data = tomllib.load(fh)
    _reject_credential_keys(data, source=str(path))
    return data


def _copy_env(values: dict[str, Any], env_key: str, config_key: str) -> None:
    if env_key in os.environ:
        values[config_key] = os.environ[env_key]


def _load_env() -> dict[str, Any]:
    """A fixed whitelist - there is no code path that forwards an arbitrary
    env var into Config, so a stray ALPACA_* env var can never leak in."""
    values: dict[str, Any] = {}
    _copy_env(values, "MONSTRA_PRO_API_URL", "monstra_pro_api_url")
    _copy_env(values, "MONSTRAPRO_DATA_DIR", "data_dir")
    _copy_env(values, "MONSTRAPRO_LOG_LEVEL", "log_level")
    _copy_env(values, "MONSTRAPRO_SQLITE_URL", "sqlite_url")
    _copy_env(values, "MONSTRAPRO_ENCRYPTION_KEY_PATH", "encryption_key_path")
    _copy_env(values, "MONSTRAPRO_RELEASE_DIR", "release_dir")
    if "MONSTRAPRO_EVENT_POLL_INTERVAL_SECONDS" in os.environ:
        values["event_poll_interval_seconds"] = os.environ["MONSTRAPRO_EVENT_POLL_INTERVAL_SECONDS"]
    return values


def load_config(overrides: Mapping[str, Any] | None = None) -> Config:
    values: dict[str, Any] = {"data_dir": _default_data_dir()}
    values.update(_load_toml(_default_config_toml_path()))
    values.update(_load_env())
    if overrides:
        values.update(overrides)

    try:
        data_dir = Path(values["data_dir"]).expanduser().resolve()

        log_level = str(values.get("log_level", "INFO")).upper()
        if log_level not in _VALID_LOG_LEVELS:
            raise ConfigError(
                f"log_level must be one of {sorted(_VALID_LOG_LEVELS)}, got {log_level!r}"
            )

        monstra_pro_api_url = str(values.get("monstra_pro_api_url", "https://monstra.pro"))
        if not monstra_pro_api_url.startswith(("http://", "https://")):
            raise ConfigError(
                f"monstra_pro_api_url must be an http(s) URL, got {monstra_pro_api_url!r}"
            )

        event_poll_interval_seconds = int(values.get("event_poll_interval_seconds", 30))
        if event_poll_interval_seconds <= 0:
            raise ConfigError(
                "event_poll_interval_seconds must be a positive integer, got "
                f"{event_poll_interval_seconds}"
            )

        default_sqlite_url = f"sqlite:///{(data_dir / 'monstrapro.db').as_posix()}"
        sqlite_url = str(values.get("sqlite_url", default_sqlite_url))
        if not sqlite_url.startswith("sqlite://"):
            raise ConfigError(f"sqlite_url must start with 'sqlite://', got {sqlite_url!r}")

        encryption_key_path = Path(values.get("encryption_key_path", data_dir / "device.key")).expanduser()
        release_dir = Path(values.get("release_dir", data_dir / "releases")).expanduser()
    except ConfigError:
        raise
    except (TypeError, ValueError) as exc:
        raise ConfigError(f"Invalid configuration value: {exc}") from exc

    data_dir.mkdir(parents=True, exist_ok=True)
    release_dir.mkdir(parents=True, exist_ok=True)

    return Config(
        data_dir=data_dir,
        sqlite_url=sqlite_url,
        encryption_key_path=encryption_key_path,
        log_level=log_level,
        monstra_pro_api_url=monstra_pro_api_url,
        event_poll_interval_seconds=event_poll_interval_seconds,
        release_dir=release_dir,
    )
