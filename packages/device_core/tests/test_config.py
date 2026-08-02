from pathlib import Path

import pytest

from device_core.config import ConfigError, load_config


def test_defaults_create_data_dir_and_release_dir(tmp_path):
    data_dir = tmp_path / "data"

    config = load_config(overrides={"data_dir": str(data_dir)})

    assert config.data_dir == data_dir.resolve()
    assert config.data_dir.exists()
    # Off-Linux (this test suite's actual runtime), release_dir stays nested
    # under data_dir - see test_release_dir_is_opt_monstrapro_on_linux for
    # the real-deployment-target (Linux) default of /opt/monstrapro.
    assert config.release_dir == config.data_dir / "releases"
    assert config.release_dir.exists()
    assert config.encryption_key_path == config.data_dir / "device.key"
    assert config.sqlite_url == f"sqlite:///{(config.data_dir / 'monstrapro.db').as_posix()}"
    assert config.monstra_pro_api_url == "https://monstra.pro"
    assert config.log_level == "INFO"
    assert config.event_poll_interval_seconds == 30


def test_env_overrides_win_over_defaults(tmp_path, monkeypatch):
    monkeypatch.setenv("MONSTRA_PRO_API_URL", "https://dev.monstra.pro")
    monkeypatch.setenv("MONSTRAPRO_LOG_LEVEL", "debug")
    monkeypatch.setenv("MONSTRAPRO_EVENT_POLL_INTERVAL_SECONDS", "5")

    config = load_config(overrides={"data_dir": str(tmp_path / "data")})

    assert config.monstra_pro_api_url == "https://dev.monstra.pro"
    assert config.log_level == "DEBUG"
    assert config.event_poll_interval_seconds == 5


def test_toml_layer_is_overridden_by_env(tmp_path, monkeypatch):
    toml_path = tmp_path / "config.toml"
    toml_path.write_text('monstra_pro_api_url = "https://toml.example"\nlog_level = "warning"\n')
    monkeypatch.setenv("MONSTRAPRO_CONFIG_FILE", str(toml_path))

    config = load_config(overrides={"data_dir": str(tmp_path / "data")})
    assert config.monstra_pro_api_url == "https://toml.example"
    assert config.log_level == "WARNING"

    monkeypatch.setenv("MONSTRA_PRO_API_URL", "https://env-wins.example")
    config = load_config(overrides={"data_dir": str(tmp_path / "data2")})
    assert config.monstra_pro_api_url == "https://env-wins.example"


@pytest.mark.parametrize(
    "overrides",
    [
        {"log_level": "not-a-level"},
        {"monstra_pro_api_url": "not-a-url"},
        {"sqlite_url": "postgresql:///nope"},
        {"event_poll_interval_seconds": 0},
        {"event_poll_interval_seconds": -5},
    ],
)
def test_invalid_values_raise_config_error(tmp_path, overrides):
    overrides = {"data_dir": str(tmp_path / "data"), **overrides}
    with pytest.raises(ConfigError):
        load_config(overrides=overrides)


def test_toml_file_with_alpaca_key_is_rejected(tmp_path, monkeypatch):
    toml_path = tmp_path / "config.toml"
    toml_path.write_text('alpaca_api_key = "should-never-be-here"\n')
    monkeypatch.setenv("MONSTRAPRO_CONFIG_FILE", str(toml_path))

    with pytest.raises(ConfigError, match="alpaca_api_key"):
        load_config(overrides={"data_dir": str(tmp_path / "data")})


def test_toml_file_with_credential_key_is_rejected(tmp_path, monkeypatch):
    toml_path = tmp_path / "config.toml"
    toml_path.write_text('some_credential = "nope"\n')
    monkeypatch.setenv("MONSTRAPRO_CONFIG_FILE", str(toml_path))

    with pytest.raises(ConfigError, match="some_credential"):
        load_config(overrides={"data_dir": str(tmp_path / "data")})


def test_release_dir_is_opt_monstrapro_on_linux(tmp_path, monkeypatch):
    """On the real deployment target, releases live under /opt (replaceable
    application code) independent of data_dir under /var/lib (persistent
    data) - image/systemd/*.service's WorkingDirectory=/opt/monstrapro/current
    depends on this exact default. mkdir is stubbed out since this test
    doesn't run as a user with permission to create /opt/monstrapro on the
    Linux CI/dev host either."""
    monkeypatch.setattr("device_core.config.platform.system", lambda: "Linux")
    monkeypatch.setattr("device_core.config.Path.mkdir", lambda self, **kwargs: None)

    config = load_config(overrides={"data_dir": str(tmp_path / "data")})

    assert config.release_dir == Path("/opt/monstrapro")


def test_release_dir_override_still_wins_on_linux(tmp_path, monkeypatch):
    monkeypatch.setattr("device_core.config.platform.system", lambda: "Linux")
    monkeypatch.setattr("device_core.config.Path.mkdir", lambda self, **kwargs: None)

    config = load_config(overrides={"data_dir": str(tmp_path / "data"), "release_dir": str(tmp_path / "custom")})

    assert config.release_dir == tmp_path / "custom"
