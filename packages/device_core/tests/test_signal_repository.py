from datetime import datetime, timedelta, timezone

from device_core.db.session import Database
from device_core.repositories.signals import SignalRepository


def test_duplicate_signal_is_not_rewritten(config):
    db = Database(config)
    repo = SignalRepository(db)

    first = repo.store(bot_id="alpha1", bot_type="alpha1", signal="buy", payload={"target_weights": {"AAPL": 1.0}})
    second = repo.store(bot_id="alpha1", bot_type="alpha1", signal="buy", payload={"target_weights": {"AAPL": 1.0}})

    assert first.written is True
    assert second.written is False
    assert second.id == first.id
    assert repo.count_for("alpha1", "alpha1") == 1


def test_changed_signal_is_written(config):
    db = Database(config)
    repo = SignalRepository(db)

    repo.store(bot_id="alpha1", bot_type="alpha1", signal="buy", payload={"target_weights": {"AAPL": 1.0}})
    changed = repo.store(bot_id="alpha1", bot_type="alpha1", signal="sell", payload={})

    assert changed.written is True
    assert repo.count_for("alpha1", "alpha1") == 2
    assert repo.latest("alpha1", "alpha1")["signal"] == "sell"


def test_different_bots_do_not_dedupe_against_each_other(config):
    db = Database(config)
    repo = SignalRepository(db)

    repo.store(bot_id="alpha1", bot_type="alpha1", signal="buy", payload={})
    result = repo.store(bot_id="alpha2", bot_type="alpha2", signal="buy", payload={})

    assert result.written is True


def test_latest_returns_none_for_unknown_bot(config):
    db = Database(config)
    repo = SignalRepository(db)
    assert repo.latest("nope", "nope") is None


def test_as_of_returns_the_signal_in_effect_at_a_past_cycle(config):
    """For trading_worker.audit's algorithm-fidelity replay: as_of() must
    return whatever was the LATEST signal at or before the given timestamp,
    not simply the newest row overall."""
    db = Database(config)
    repo = SignalRepository(db)
    now = datetime.now(timezone.utc)

    repo.store(bot_id="alpha1", bot_type="alpha1", signal="buy", payload={"target_weights": {"AAPL": 1.0}}, ts=now - timedelta(hours=1))
    repo.store(bot_id="alpha1", bot_type="alpha1", signal="sell", payload={}, ts=now)

    as_of_between = repo.as_of("alpha1", "alpha1", now - timedelta(minutes=30))
    assert as_of_between["signal"] == "buy"

    as_of_now = repo.as_of("alpha1", "alpha1", now)
    assert as_of_now["signal"] == "sell"


def test_as_of_returns_none_when_no_signal_existed_yet(config):
    db = Database(config)
    repo = SignalRepository(db)
    now = datetime.now(timezone.utc)

    repo.store(bot_id="alpha1", bot_type="alpha1", signal="buy", payload={}, ts=now)

    assert repo.as_of("alpha1", "alpha1", now - timedelta(days=1)) is None
