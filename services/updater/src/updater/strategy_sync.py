"""Applies the data half of a release manifest: algorithm universe/param
updates (Objectives.txt) and notification banners. Independent of the
software-release apply pipeline in release_store.py/main.py — a manifest
can carry strategy updates with no new software version at all (e.g. a
routine universe refresh), and this runs regardless of whether a software
update is also pending.

Shape note (see manifest_client.py's module docstring for the full
picture): this still treats `manifest.strategy_updates[bot_slug]` as flat
params to merge, and only for a bot_slug that already has a local
strategy_config row. The real NextJS_Monsta endpoint's shape is now
`{botType, params}` per bot, and nothing here yet provisions a brand-new
strategy_config row for a bot the device has never run before - both need
fixing together once a real ReleaseManifestClient replaces NullManifestClient.
"""

from __future__ import annotations

from device_core.core import DeviceCore
from device_core.events import EventType

from updater.manifest_client import ReleaseManifest


def sync_strategy_updates(core: DeviceCore, manifest: ReleaseManifest) -> list[str]:
    """Merge `manifest.strategy_updates` into local strategy_config rows.

    Only touches rows whose `source` is "monstra.pro" - a bot the owner
    configured locally (source="local") is never overwritten by a
    server-pushed update. Returns the bot_slugs actually updated.
    """
    updated: list[str] = []
    for bot_slug, partial_params in manifest.strategy_updates.items():
        existing = core.strategies.get(bot_slug)
        if existing is None or existing.get("source") != "monstra.pro":
            continue

        merged_params = {**(existing.get("params_json") or {}), **partial_params}
        core.strategies.upsert(
            bot_slug=bot_slug,
            display_name=existing.get("display_name"),
            params=merged_params,
            target_allocation=existing.get("target_allocation_json"),
            is_active=existing.get("is_active", True),
            source="monstra.pro",
        )
        updated.append(bot_slug)

    return updated


def publish_notifications(core: DeviceCore, manifest: ReleaseManifest) -> int:
    """Publish one device_event per manifest notification (new bots,
    update-required notices, ...) for display's banner to pick up. Returns
    the count published."""
    for note in manifest.notifications:
        core.events.publish(
            EventType.NOTIFICATION,
            {"message": note.get("message", "")},
            severity=note.get("severity", "info"),
        )
    return len(manifest.notifications)
