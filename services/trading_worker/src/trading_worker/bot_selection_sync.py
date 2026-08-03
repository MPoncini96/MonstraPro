"""Syncs the owner's website bot selections into the device's own local
strategy_config table - the piece that was missing entirely until now:
5+ bots selected on monstra.pro's /devices/[deviceId]/bots page never
reached the device, because nothing here ever called
GET /api/devices/strategy-config (NextJS_Monsta's
src/app/api/devices/strategy-config/route.ts - authored specifically for
this, per that route's own docstring: "What trading_worker pulls once
activated"). run_cycle only ever iterates device_core's local
strategy_config rows (core.strategies.get_active()), so without this sync
a device could have any number of bots selected on the website and still
run zero of them, on any schedule, forever.

Only ever touches strategy_config rows with source="monstra.pro" - a bot
the owner configured locally (source="local", e.g. via tests or manual
seeding) is never overwritten or deactivated by this sync, mirroring
updater/strategy_sync.py's identical "never touch a locally-configured
bot" rule on the software-release side.
"""

from __future__ import annotations

import logging
from typing import Any

import requests

from device_core.core import DeviceCore

logger = logging.getLogger(__name__)


def sync_bot_selections(core: DeviceCore, *, timeout_seconds: float = 10.0, session: Any = None) -> bool:
    """Returns True if the sync round-tripped successfully (regardless of
    whether anything actually changed locally). Every network failure is
    treated as "sync again next call" rather than raised, matching this
    module's siblings' (activation.py, alpaca_sync.py, run_request.py)
    resilience philosophy - a transient connectivity blip must never itself
    interrupt a trading cycle.
    """
    token = core.devices.get_device_token()
    if token is None:
        return False

    http = session if session is not None else requests
    try:
        response = http.get(
            f"{core.config.monstra_pro_api_url}/api/devices/strategy-config",
            headers={"Authorization": f"Bearer {token}"},
            timeout=timeout_seconds,
        )
        response.raise_for_status()
        body = response.json()
    except Exception:
        logger.warning("strategy-config sync with monstra.pro failed; will retry", exc_info=True)
        return False

    selected_slugs: set[str] = set()
    for bot in body.get("bots") or []:
        bot_slug = bot.get("botSlug")
        bot_type = bot.get("botType")
        if not bot_slug or not bot_type:
            continue

        existing = core.strategies.get(bot_slug)
        if existing is not None and existing.get("source") == "local":
            # Never clobber a bot the owner (or a test) configured directly
            # on this device, even if monstra.pro happens to select a bot
            # with the same slug.
            continue

        selected_slugs.add(bot_slug)
        core.strategies.upsert(
            bot_slug=bot_slug,
            bot_type=bot_type,
            equity_weight=bot.get("equityWeight"),
            display_name=(existing or {}).get("display_name") or bot_slug,
            params=bot.get("params") or {},
            target_allocation=(existing or {}).get("target_allocation_json"),
            is_active=True,
            source="monstra.pro",
        )

    # A bot the owner removed on the website must stop trading here too -
    # deactivate any monstra.pro-sourced row no longer in the current
    # selection, rather than leaving it running forever on stale consent.
    for row in core.strategies.list_by_source("monstra.pro"):
        if row["is_active"] and row["bot_slug"] not in selected_slugs:
            core.strategies.upsert(
                bot_slug=row["bot_slug"],
                bot_type=row.get("bot_type"),
                equity_weight=row.get("equity_weight"),
                display_name=row.get("display_name"),
                params=row.get("params_json") or {},
                target_allocation=row.get("target_allocation_json"),
                is_active=False,
                source="monstra.pro",
            )

    return True
