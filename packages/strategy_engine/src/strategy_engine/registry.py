"""Algorithm registry.

Ports the pattern from Monstra-Worker/algorithm_registry.py: a single
source of truth mapping a strategy slug to its metadata and a lazily
imported runner function, so trading_worker depends on slugs, not concrete
bot modules.

Trimmed for a single-owner appliance: no worker_minute_offset (Pro Box
schedules its own single trading loop, not a shared multi-bot cron), no
fallback_bot_ids/db_table/backfill dispatcher (those are multi-tenant SaaS
concerns from Monstra-Worker's worker.py that don't apply here — see
ARCHITECTURE.md section 2). Only the three bots Monstra.Pro Box ships with
for now are registered: force (alpha1), aptet, draco.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable

from strategy_engine.bot_identity import BOT_TYPE_ALPHA1, BOT_TYPE_APTET, BOT_TYPE_DRACO

RunnerFn = Callable[[dict[str, Any], dict[str, Any] | None], dict[str, Any]]


@dataclass(frozen=True)
class AlgorithmEntry:
    """Metadata for one algorithm family.

    Attributes
    ----------
    slug:
        Canonical string key used in strategy_config rows and registry
        lookups. Matches the slug monstra.pro's officialBotRegistry.ts uses
        for the same algorithm family (e.g. "force" for the alpha1 engine).
    bot_type:
        One of strategy_engine.bot_identity.BOT_TYPE_* — identifies which
        run_<bot> module implements this algorithm.
    display_name:
        Human-readable algorithm name shown in logs and on the device
        display.
    alias:
        Short marketing alias, mirrors monstra.pro UI copy.
    """

    slug: str
    bot_type: str
    display_name: str
    alias: str


ALGORITHM_REGISTRY: tuple[AlgorithmEntry, ...] = (
    AlgorithmEntry(slug="force", bot_type=BOT_TYPE_ALPHA1, display_name="Force", alias="Force"),
    AlgorithmEntry(slug="aptet", bot_type=BOT_TYPE_APTET, display_name="Aptet", alias="Aptet"),
    AlgorithmEntry(slug="draco", bot_type=BOT_TYPE_DRACO, display_name="Draco", alias="Draco"),
)

_REGISTRY_BY_SLUG: dict[str, AlgorithmEntry] = {e.slug: e for e in ALGORITHM_REGISTRY}

assert len(_REGISTRY_BY_SLUG) == len(ALGORITHM_REGISTRY), "Duplicate slug detected in ALGORITHM_REGISTRY"


def get_algorithm(slug: str) -> AlgorithmEntry | None:
    """Return the AlgorithmEntry for *slug*, or None if unknown."""
    return _REGISTRY_BY_SLUG.get(slug.strip().lower())


def active_slugs() -> list[str]:
    """Return every registered slug, in registration order."""
    return [e.slug for e in ALGORITHM_REGISTRY]


# ---------------------------------------------------------------------------
# Lazy runner registry
# ---------------------------------------------------------------------------
# Maps slug -> callable(config, state) -> signal dict. Registered lazily so
# importing `registry` does not pull in every bot module's dependencies
# (numpy/pandas) unless a runner is actually requested.

_RUNNER_FACTORIES: dict[str, Callable[[], RunnerFn]] = {}
_cached_runners: dict[str, RunnerFn] = {}


def register_runner(slug: str, factory: Callable[[], RunnerFn]) -> None:
    """Register a lazy factory that returns the runner for *slug*.

    Example::

        from strategy_engine.registry import register_runner

        register_runner("force", lambda: __import__(
            "strategy_engine.bots.alpha1", fromlist=["run_alpha1"]
        ).run_alpha1)
    """
    slug_normalized = slug.strip().lower()
    if slug_normalized not in _REGISTRY_BY_SLUG:
        raise ValueError(
            f"Cannot register runner for unknown slug {slug!r}. "
            f"Add an AlgorithmEntry to ALGORITHM_REGISTRY first."
        )
    _RUNNER_FACTORIES[slug_normalized] = factory


def get_runner(slug: str) -> RunnerFn | None:
    """Return the runner callable for *slug*, or None if none registered."""
    slug_normalized = slug.strip().lower()
    if slug_normalized in _cached_runners:
        return _cached_runners[slug_normalized]
    factory = _RUNNER_FACTORIES.get(slug_normalized)
    if factory is None:
        return None
    runner = factory()
    _cached_runners[slug_normalized] = runner
    return runner


def _register_default_runners() -> None:
    register_runner(
        "force",
        lambda: __import__("strategy_engine.bots.alpha1", fromlist=["run_alpha1"]).run_alpha1,
    )
    register_runner(
        "aptet",
        lambda: __import__("strategy_engine.bots.aptet", fromlist=["run_aptet"]).run_aptet,
    )
    register_runner(
        "draco",
        lambda: __import__("strategy_engine.bots.draco", fromlist=["run_draco"]).run_draco,
    )


_register_default_runners()
