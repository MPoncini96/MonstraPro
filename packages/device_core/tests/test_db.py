from device_core.config import load_config
from device_core.db.database import Database
from device_core.device import Device


def _database(tmp_path):
    config = load_config(overrides={"data_dir": str(tmp_path)})
    return Database(config)


def test_store_and_get_latest_signal(tmp_path):
    db = _database(tmp_path)

    db.store_signal(
        bot_id="alpha1",
        bot_type="alpha1",
        signal="buy",
        note="initial signal",
        payload={"target_weights": {"AAPL": 1.0}},
    )
    db.store_signal(bot_id="alpha1", bot_type="alpha1", signal="sell", payload={})

    latest = db.get_latest_signal("alpha1", "alpha1")
    assert latest is not None
    assert latest["signal"] == "sell"

    other = db.get_latest_signal("alpha2", "alpha2")
    assert other is None


def test_store_order_and_update_status(tmp_path):
    db = _database(tmp_path)

    order_id = db.store_order(bot_slug="alpha1", symbol="AAPL", side="buy", qty=10)
    db.update_order_status(order_id, status="filled", raw_response={"id": "abc123"})

    with db.session() as session:
        from device_core.db.models import Order

        row = session.get(Order, order_id)
        assert row.status == "filled"
        assert row.raw_response_json == {"id": "abc123"}


def test_alpaca_credentials_are_encrypted_at_rest(tmp_path):
    db = _database(tmp_path)

    db.set_alpaca_credentials(
        api_key="AKPUBLIC123", api_secret="SUPERSECRET456", base_url="https://paper-api.alpaca.markets"
    )
    creds = db.get_alpaca_credentials()

    assert creds["api_key"] == "AKPUBLIC123"
    assert creds["api_secret"] == "SUPERSECRET456"
    assert creds["mode"] == "paper"

    raw_db_bytes = db.config.db_path.read_bytes()
    assert b"SUPERSECRET456" not in raw_db_bytes


def test_strategy_config_upsert_is_idempotent_per_slug(tmp_path):
    db = _database(tmp_path)

    db.upsert_strategy_config(bot_slug="alpha1", target_allocation={"AAPL": 1.0})
    db.upsert_strategy_config(bot_slug="alpha1", target_allocation={"AAPL": 0.5, "MSFT": 0.5})

    active = db.get_active_strategy_configs()
    assert len(active) == 1
    assert active[0]["target_allocation_json"] == {"AAPL": 0.5, "MSFT": 0.5}


def test_cache_market_data_skips_duplicates(tmp_path):
    db = _database(tmp_path)
    from datetime import datetime, timezone

    bar = {"symbol": "AAPL", "ts": datetime(2026, 1, 2, tzinfo=timezone.utc), "close": 190.0, "source": "alpaca"}

    first = db.cache_market_data([bar])
    second = db.cache_market_data([bar])

    assert first == 1
    assert second == 0


def test_software_release_lifecycle(tmp_path):
    db = _database(tmp_path)

    db.record_software_release(version="0.1.0", status="active")
    db.record_software_release(version="0.2.0", status="staged")
    db.mark_release_active("0.2.0")

    with db.session() as session:
        from device_core.db.models import SoftwareRelease

        rows = {row.version: row.status for row in session.query(SoftwareRelease).all()}
        assert rows == {"0.1.0": "rolled_back", "0.2.0": "active"}


def test_device_load_creates_row_and_activates(tmp_path):
    db = _database(tmp_path)

    device = Device.load(db)
    assert device.is_activated is False
    assert device.serial.startswith("MPB-")

    activated = device.activate(db, owner_ref="cust_123")
    assert activated.is_activated is True
    assert activated.owner_ref == "cust_123"

    reloaded = Device.load(db)
    assert reloaded.id == device.id
    assert reloaded.is_activated is True
    assert reloaded.serial == device.serial
