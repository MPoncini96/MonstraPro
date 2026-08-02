import pytest

from device_core.core import DeviceCore

_ENV_VARS = (
    "MONSTRAPRO_CONFIG_FILE",
    "MONSTRA_PRO_API_URL",
    "MONSTRAPRO_DATA_DIR",
    "MONSTRAPRO_LOG_LEVEL",
    "MONSTRAPRO_EVENT_POLL_INTERVAL_SECONDS",
    "MONSTRAPRO_SQLITE_URL",
    "MONSTRAPRO_ENCRYPTION_KEY_PATH",
    "MONSTRAPRO_RELEASE_DIR",
)


@pytest.fixture(autouse=True)
def _clean_env(monkeypatch):
    """Isolate every test from whatever's actually in the real environment
    or a real /etc/monstrapro/config.toml on the machine running tests."""
    for var in _ENV_VARS:
        monkeypatch.delenv(var, raising=False)


@pytest.fixture
def core(tmp_path):
    return DeviceCore.load(overrides={"data_dir": str(tmp_path / "data")})
