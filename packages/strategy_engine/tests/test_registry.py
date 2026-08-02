import pytest

from strategy_engine.registry import (
    ALGORITHM_REGISTRY,
    active_slugs,
    get_algorithm,
    get_runner,
    register_runner,
)


def test_registry_has_exactly_the_three_shipped_bots():
    assert active_slugs() == ["force", "aptet", "draco"]


def test_get_algorithm_is_case_and_whitespace_insensitive():
    entry = get_algorithm(" Force ")
    assert entry is not None
    assert entry.slug == "force"
    assert entry.bot_type == "alpha1"


def test_get_algorithm_unknown_slug_returns_none():
    assert get_algorithm("nonexistent") is None


@pytest.mark.parametrize("slug", ["force", "aptet", "draco"])
def test_get_runner_resolves_and_caches(slug):
    runner = get_runner(slug)
    assert callable(runner)
    assert get_runner(slug) is runner  # cached, same object second time


def test_get_runner_unknown_slug_returns_none():
    assert get_runner("nonexistent") is None


def test_register_runner_rejects_unknown_slug():
    with pytest.raises(ValueError):
        register_runner("nonexistent", lambda: (lambda config, state=None: {}))


def test_registry_slugs_are_unique():
    slugs = [entry.slug for entry in ALGORITHM_REGISTRY]
    assert len(slugs) == len(set(slugs))
