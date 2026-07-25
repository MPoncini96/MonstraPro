from device_core.core import DeviceCore
from device_core.events import EventType


def test_load_from_empty_directory(tmp_path):
    core = DeviceCore.load(overrides={"data_dir": str(tmp_path / "data")})

    assert core.config.data_dir.exists()
    assert core.config.data_dir == (tmp_path / "data").resolve()

    db_path = core.config.sqlite_url.removeprefix("sqlite:///")
    from pathlib import Path

    assert Path(db_path).exists()

    device = core.devices.get_or_create()
    assert device.is_activated is False


def test_state_persists_across_reopen(tmp_path):
    overrides = {"data_dir": str(tmp_path / "data")}

    core1 = DeviceCore.load(overrides=overrides)
    device = core1.devices.get_or_create()
    core1.credentials.save(
        mode="paper", api_key="PAPER_KEY", api_secret="PAPER_SECRET", base_url="https://paper-api.alpaca.markets"
    )
    core1.signals.store(bot_id="alpha1", bot_type="alpha1", signal="buy", payload={"target_weights": {"AAPL": 1.0}})
    event_id = core1.events.publish(EventType.TRADE_EXECUTED, {"bot_slug": "alpha1"})
    core1.close()

    core2 = DeviceCore.load(overrides=overrides)

    reloaded_device = core2.devices.get()
    assert reloaded_device.id == device.id
    assert reloaded_device.serial == device.serial

    creds = core2.credentials.get("paper")
    assert creds["api_key"] == "PAPER_KEY"

    signal = core2.signals.latest("alpha1", "alpha1")
    assert signal["signal"] == "buy"

    unconsumed = core2.events.list_unconsumed()
    assert any(event["id"] == event_id for event in unconsumed)


def test_full_public_api_surface_is_present(tmp_path):
    core = DeviceCore.load(overrides={"data_dir": str(tmp_path / "data")})

    for attr in (
        "config",
        "database",
        "devices",
        "credentials",
        "strategies",
        "allocations",
        "signals",
        "events",
        "logs",
        "vault",
    ):
        assert hasattr(core, attr)
