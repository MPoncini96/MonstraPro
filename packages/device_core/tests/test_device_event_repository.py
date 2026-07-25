import pytest

from device_core.db.session import Database
from device_core.events import EventType
from device_core.repositories.device_event import DeviceEventRepository


def test_events_preserve_publish_order(config):
    db = Database(config)
    repo = DeviceEventRepository(db)

    repo.publish(EventType.TRADE_EXECUTED, {"bot_slug": "alpha1"})
    repo.publish(EventType.WIFI_DISCONNECTED, {"reason": "timeout"})
    repo.publish(EventType.FATAL_ERROR, {"detail": "boom"}, severity="critical")

    unconsumed = repo.list_unconsumed()
    assert [event["type"] for event in unconsumed] == [
        "trade_executed",
        "wifi_disconnected",
        "fatal_error",
    ]
    assert unconsumed[-1]["severity"] == "critical"


def test_mark_consumed_removes_event_from_unconsumed_list(config):
    db = Database(config)
    repo = DeviceEventRepository(db)

    first_id = repo.publish(EventType.TRADE_EXECUTED, {"bot_slug": "alpha1"})
    repo.publish(EventType.WIFI_CONNECTED)

    repo.mark_consumed(first_id, consumer="display")

    remaining = repo.list_unconsumed()
    assert len(remaining) == 1
    assert remaining[0]["type"] == "wifi_connected"


def test_events_stay_unconsumed_until_acknowledged(config):
    db = Database(config)
    repo = DeviceEventRepository(db)

    repo.publish(EventType.DEVICE_ACTIVATED)

    assert len(repo.list_unconsumed()) == 1
    assert len(repo.list_unconsumed()) == 1  # polling again doesn't consume it


def test_publish_accepts_plain_string_event_type(config):
    db = Database(config)
    repo = DeviceEventRepository(db)

    repo.publish("custom_event", {"foo": "bar"})

    [event] = repo.list_unconsumed()
    assert event["type"] == "custom_event"


def test_invalid_severity_rejected(config):
    db = Database(config)
    repo = DeviceEventRepository(db)

    with pytest.raises(ValueError):
        repo.publish(EventType.FATAL_ERROR, severity="not-a-real-severity")


def test_mark_consumed_unknown_id_raises(config):
    db = Database(config)
    repo = DeviceEventRepository(db)

    with pytest.raises(ValueError):
        repo.mark_consumed(999, consumer="display")
