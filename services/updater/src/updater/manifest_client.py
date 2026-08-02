"""Release manifest fetch — the seam for monstra.pro's device-status /
release-manifest endpoint (ARCHITECTURE.md section 9).

As of NextJS_Monsta's Track B1/B2 work, GET /api/devices/manifest is real
(device-token authenticated) - see that repo's
src/app/api/devices/manifest/route.ts. No HTTPManifestClient exists here
yet though; still NullManifestClient below, same seam pattern as
trading_worker/activation.py's ActivationClient, so swapping one in is a
one-file change whenever that wiring pass happens.

Known shape gap when that client gets built: the real endpoint's
`strategyUpdates[botSlug]` is `{botType, params}`, not flat params -
`botSlug` there is a specific monster variation (e.g. "vectura_draco"),
and `botType` (force/aptet/draco) is what strategy_engine.registry.get_runner()
actually needs to pick a runner. strategy_sync.py's sync_strategy_updates
below still assumes flat params and only merges into an *existing*
strategy_config row - both need updating together with the real client,
not before (nothing exercises this shape yet).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Protocol


@dataclass(frozen=True)
class ReleaseManifest:
    version: str
    artifact_url: str | None = None
    artifact_signature: str | None = None
    # bot_slug -> partial params to merge into that bot's local
    # strategy_config row (Objectives.txt's "algorithm universe updates").
    # See module docstring: the real endpoint's shape has moved on from
    # this (now {botType, params} per bot) - update together.
    strategy_updates: dict[str, dict] = field(default_factory=dict)
    # Each: {"message": str, "severity": "info"|"warning"|"error"}.
    notifications: list[dict] = field(default_factory=list)


class ReleaseManifestClient(Protocol):
    def fetch(self) -> ReleaseManifest | None:
        """Return the current manifest, or None if it can't be fetched
        (network down, device not activated, endpoint doesn't exist yet)."""
        ...


class NullManifestClient:
    """Always reports "nothing to fetch" — honest placeholder until
    monstra.pro's manifest endpoint exists, rather than fabricating a
    manifest shape nothing on the server side has agreed to yet."""

    def fetch(self) -> ReleaseManifest | None:
        return None
