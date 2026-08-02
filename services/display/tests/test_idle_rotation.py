from datetime import datetime, timezone

from display.idle_rotation import CYCLE_SECONDS, IdlePhase, phase_at


def _at(elapsed_seconds: float) -> datetime:
    return datetime.fromtimestamp(elapsed_seconds, tz=timezone.utc)


def test_cycle_length_is_40_seconds():
    assert CYCLE_SECONDS == 40


def test_starts_in_portfolio_phase():
    state = phase_at(_at(0))
    assert state.phase == IdlePhase.PORTFOLIO
    assert state.cycle_index == 0


def test_portfolio_phase_lasts_15_seconds():
    assert phase_at(_at(14.9)).phase == IdlePhase.PORTFOLIO
    assert phase_at(_at(15.0)).phase == IdlePhase.BOT


def test_bot_phase_lasts_15_seconds():
    assert phase_at(_at(15.0)).phase == IdlePhase.BOT
    assert phase_at(_at(29.9)).phase == IdlePhase.BOT
    assert phase_at(_at(30.0)).phase == IdlePhase.STOCK


def test_stock_phase_lasts_10_seconds():
    assert phase_at(_at(30.0)).phase == IdlePhase.STOCK
    assert phase_at(_at(39.9)).phase == IdlePhase.STOCK


def test_cycle_repeats_with_incremented_cycle_index():
    state = phase_at(_at(40.0))
    assert state.phase == IdlePhase.PORTFOLIO
    assert state.cycle_index == 1

    state = phase_at(_at(55.0))
    assert state.phase == IdlePhase.BOT
    assert state.cycle_index == 1

    state = phase_at(_at(80.0))
    assert state.phase == IdlePhase.PORTFOLIO
    assert state.cycle_index == 2


def test_cycle_index_is_stable_within_a_single_phase():
    a = phase_at(_at(15.0))
    b = phase_at(_at(29.0))
    assert a.cycle_index == b.cycle_index == 0
