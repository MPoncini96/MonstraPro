from updater.manifest_client import ReleaseManifest
from updater.strategy_sync import publish_notifications, sync_strategy_updates


def test_updates_server_sourced_bot(core):
    core.strategies.upsert(bot_slug="force", params={"universe": ["AAPL"]}, source="monstra.pro")
    manifest = ReleaseManifest(version="1.0.0", strategy_updates={"force": {"universe": ["AAPL", "MSFT"]}})

    updated = sync_strategy_updates(core, manifest)

    assert updated == ["force"]
    assert core.strategies.get("force")["params_json"] == {"universe": ["AAPL", "MSFT"]}


def test_does_not_touch_locally_sourced_bot(core):
    core.strategies.upsert(bot_slug="force", params={"universe": ["AAPL"]}, source="local")
    manifest = ReleaseManifest(version="1.0.0", strategy_updates={"force": {"universe": ["AAPL", "MSFT"]}})

    updated = sync_strategy_updates(core, manifest)

    assert updated == []
    assert core.strategies.get("force")["params_json"] == {"universe": ["AAPL"]}


def test_ignores_updates_for_bots_not_configured_locally(core):
    manifest = ReleaseManifest(version="1.0.0", strategy_updates={"draco": {"universe": ["NVDA"]}})

    updated = sync_strategy_updates(core, manifest)

    assert updated == []
    assert core.strategies.get("draco") is None


def test_merge_preserves_existing_params_not_present_in_update(core):
    core.strategies.upsert(
        bot_slug="force",
        params={"universe": ["AAPL"], "top_n": 4},
        source="monstra.pro",
    )
    manifest = ReleaseManifest(version="1.0.0", strategy_updates={"force": {"universe": ["AAPL", "MSFT"]}})

    sync_strategy_updates(core, manifest)

    assert core.strategies.get("force")["params_json"] == {"universe": ["AAPL", "MSFT"], "top_n": 4}


def test_publish_notifications_emits_one_event_per_notification(core):
    manifest = ReleaseManifest(
        version="1.0.0",
        notifications=[
            {"message": "New bot available: Draco v2", "severity": "info"},
            {"message": "Update required", "severity": "warning"},
        ],
    )

    count = publish_notifications(core, manifest)

    assert count == 2
    events = core.events.list_unconsumed()
    assert [e["type"] for e in events] == ["notification", "notification"]
    assert events[0]["payload_json"] == {"message": "New bot available: Draco v2"}
    assert events[1]["severity"] == "warning"
