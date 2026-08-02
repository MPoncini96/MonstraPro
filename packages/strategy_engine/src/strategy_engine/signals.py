"""Signal shape shared between strategy_engine and trading_worker.

Every `run_<bot>(config, state=None)` function in `strategy_engine.bots`
returns a plain dict matching this shape (kept as a dict, not a dataclass
instance, so the field names stay identical to Monstra-Worker's signal dict
— see Monstra-Worker/bots/alpha1.py and worker.py::run_bot — and ported bot
code doesn't need reshaping). `Signal` here is a typed view over that dict
for callers (trading_worker) that want attribute access and validation
before writing to `device_core.repositories.SignalRepository`.

    bot_id:  the strategy_config row's slug this signal was generated for.
    bot_type: one of strategy_engine.bot_identity.BOT_TYPE_*.
    ts: UTC timestamp the signal was generated.
    signal: "HOLD" or "REBALANCE".
    note: human-readable summary, shown on the device display.
    payload: strategy-specific detail, always including `target_weights`
        (ticker -> portfolio weight, summing to <= 1.0).
    state: updated adaptation/position state to persist for the next run,
        or None for stateless bots (alpha1, aptet regenerate state fresh
        from price history each run; draco carries it forward run-to-run).
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any


@dataclass(frozen=True)
class Signal:
    bot_id: str
    bot_type: str
    ts: datetime
    signal: str
    note: str
    payload: dict[str, Any]
    state: dict[str, Any] | None = None

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "Signal":
        return cls(
            bot_id=data["bot_id"],
            bot_type=data["bot_type"],
            ts=data["ts"],
            signal=data["signal"],
            note=data["note"],
            payload=data.get("payload") or {},
            state=data.get("state"),
        )

    @property
    def target_weights(self) -> dict[str, float]:
        return dict(self.payload.get("target_weights") or {})

    def as_dict(self) -> dict[str, Any]:
        return {
            "bot_id": self.bot_id,
            "bot_type": self.bot_type,
            "ts": self.ts,
            "signal": self.signal,
            "note": self.note,
            "payload": self.payload,
            "state": self.state,
        }
