from device_core.config import load_config
from device_core.db.database import Database
from device_core.events import EventBus, EventType


def test_publish_and_poll_since(tmp_path):
    config = load_config(overrides={"data_dir": str(tmp_path)})
    db = Database(config)
    events = EventBus(db)

    first_id = events.publish(EventType.TRADE_EXECUTED, {"bot_slug": "alpha1"})
    events.publish(EventType.CONNECTIVITY_CHANGED, {"wifi": False})

    all_events = events.poll_since(0)
    assert [event["type"] for event in all_events] == ["trade_executed", "connectivity_changed"]

    only_new = events.poll_since(first_id)
    assert len(only_new) == 1
    assert only_new[0]["type"] == "connectivity_changed"
    assert only_new[0]["payload"] == {"wifi": False}

    assert events.latest_id() == only_new[0]["id"]


def test_publish_accepts_plain_string_type(tmp_path):
    config = load_config(overrides={"data_dir": str(tmp_path)})
    db = Database(config)
    events = EventBus(db)

    events.publish("custom_event", {"foo": "bar"})

    [event] = events.poll_since(0)
    assert event["type"] == "custom_event"
