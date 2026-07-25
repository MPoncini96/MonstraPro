from device_core.config import load_config


def test_defaults_create_data_dir(tmp_path, monkeypatch):
    monkeypatch.delenv("MONSTRA_PRO_BASE_URL", raising=False)
    monkeypatch.delenv("MONSTRAPRO_LOG_LEVEL", raising=False)
    monkeypatch.delenv("MONSTRAPRO_CONFIG_FILE", raising=False)
    data_dir = tmp_path / "data"

    config = load_config(overrides={"data_dir": str(data_dir)})

    assert config.data_dir == data_dir.resolve()
    assert config.data_dir.exists()
    assert config.db_path == config.data_dir / "monstrapro.db"
    assert config.device_key_path == config.data_dir / "device.key"
    assert config.monstra_pro_base_url == "https://monstra.pro"
    assert config.log_level == "INFO"


def test_env_overrides(tmp_path, monkeypatch):
    monkeypatch.delenv("MONSTRAPRO_CONFIG_FILE", raising=False)
    monkeypatch.setenv("MONSTRA_PRO_BASE_URL", "https://dev.monstra.pro")
    monkeypatch.setenv("MONSTRAPRO_LOG_LEVEL", "debug")
    monkeypatch.setenv("MONSTRAPRO_POLL_INTERVAL_SECONDS", "5")

    config = load_config(overrides={"data_dir": str(tmp_path / "data2")})

    assert config.monstra_pro_base_url == "https://dev.monstra.pro"
    assert config.log_level == "DEBUG"
    assert config.poll_interval_seconds == 5


def test_toml_layer_overridden_by_env(tmp_path, monkeypatch):
    toml_path = tmp_path / "config.toml"
    toml_path.write_text('monstra_pro_base_url = "https://toml.example"\nlog_level = "warning"\n')
    monkeypatch.setenv("MONSTRAPRO_CONFIG_FILE", str(toml_path))
    monkeypatch.delenv("MONSTRA_PRO_BASE_URL", raising=False)
    monkeypatch.delenv("MONSTRAPRO_LOG_LEVEL", raising=False)

    config = load_config(overrides={"data_dir": str(tmp_path / "data3")})
    assert config.monstra_pro_base_url == "https://toml.example"
    assert config.log_level == "WARNING"

    # env still wins over the toml file when both are set
    monkeypatch.setenv("MONSTRA_PRO_BASE_URL", "https://env-wins.example")
    config = load_config(overrides={"data_dir": str(tmp_path / "data4")})
    assert config.monstra_pro_base_url == "https://env-wins.example"
