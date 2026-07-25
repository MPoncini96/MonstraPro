"""Algorithm registry.

Ports the pattern from Monstra-Worker/algorithm_registry.py: a single
source of truth mapping a strategy slug to its metadata and a lazily
imported runner function, so trading_worker depends on slugs, not concrete
bot modules.

Not yet implemented — this is a placeholder for the foundational-services
pass. When implemented it should provide, at minimum:

    AlgorithmEntry        - dataclass: slug, display_name, params schema ref
    ALGORITHM_REGISTRY     - tuple of AlgorithmEntry
    get_algorithm(slug)    - lookup
    register_runner(slug, factory) / get_runner(slug) - lazy runner lookup

See Monstra-Worker/algorithm_registry.py for the proven reference
implementation this should be adapted from (drop the backfill-dispatcher
and multi-tenant fallback-bot-id concerns; a Pro Box only runs the one
strategy its owner configured).
"""
