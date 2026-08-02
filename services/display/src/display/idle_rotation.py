"""Rotates the idle screen through portfolio / bot / stock sub-views on a
fixed wall-clock cadence (Objectives: 15s portfolio candlestick, 15s bot
performance, 10s stock performance, then repeats with a different bot and
a different stock each time around).

Pure and time-driven (unlike state.StateMachine, which is event-driven) -
`phase_at(now)` is a function of wall-clock time alone, anchored to the
Unix epoch rather than "when the idle screen was last entered". That
means: no extra state to thread through main.py's loop, it's fully
deterministic/unit-testable without a running clock, and a screen that
briefly leaves idle (e.g. a trade_wake interruption) and returns resumes
the rotation where it would already be, rather than restarting from
portfolio every time.

`cycle_index` (which full 40s loop we're in) is what main.py uses to pick
*which* bot or stock to show this time around - `bots[cycle_index %
len(bots)]` - so consecutive cycles naturally show different ones without
this module needing to know how many bots or stocks exist.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum

PORTFOLIO_SECONDS = 15
BOT_SECONDS = 15
STOCK_SECONDS = 10
CYCLE_SECONDS = PORTFOLIO_SECONDS + BOT_SECONDS + STOCK_SECONDS  # 40


class IdlePhase(StrEnum):
    PORTFOLIO = "portfolio"
    BOT = "bot"
    STOCK = "stock"


@dataclass(frozen=True)
class IdleRotationState:
    phase: IdlePhase
    cycle_index: int


def phase_at(now: datetime) -> IdleRotationState:
    elapsed = now.timestamp()
    position = elapsed % CYCLE_SECONDS
    cycle_index = int(elapsed // CYCLE_SECONDS)

    if position < PORTFOLIO_SECONDS:
        return IdleRotationState(IdlePhase.PORTFOLIO, cycle_index)
    if position < PORTFOLIO_SECONDS + BOT_SECONDS:
        return IdleRotationState(IdlePhase.BOT, cycle_index)
    return IdleRotationState(IdlePhase.STOCK, cycle_index)
