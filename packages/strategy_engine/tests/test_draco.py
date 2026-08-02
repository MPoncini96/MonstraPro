import pytest

from strategy_engine.bots.draco import run_draco
from strategy_engine.bot_identity import BOT_TYPE_DRACO
from tests.conftest import geometric_series, make_bars_frame


def _patch_bars(monkeypatch, frame):
    monkeypatch.setattr(
        "strategy_engine.bots.draco.get_daily_bars",
        lambda symbols, start, end, adjusted=True: frame,
    )


def test_run_draco_falls_back_when_regime_ticker_missing(monkeypatch):
    # The mock ignores `symbols` and always returns a single-column frame, so
    # download_draco_prices ends up with a column named after the *first*
    # requested ticker only ("TREND") — "SPY" (market_regime_ticker) is
    # missing, which is exactly the "insufficient price history" path.
    frame = make_bars_frame({"TREND": [100.0, 101.0]})
    _patch_bars(monkeypatch, frame)

    config = {"bot_id": "test-draco", "universe": ["TREND"], "market_regime_ticker": "SPY", "fallback_ticker": "CASH"}
    result = run_draco(config)

    assert result["bot_type"] == BOT_TYPE_DRACO
    # Fallback allocates fully into the fallback ticker, so this is a
    # REBALANCE (into cash), not a HOLD — HOLD is reserved for "no fallback
    # ticker configured at all".
    assert result["signal"] == "REBALANCE"
    assert result["payload"]["target_weights"] == {"CASH": 1.0}
    assert result["state"] is not None  # normalized empty state, even on early fallback


def test_run_draco_circuit_breaker_liquidates_on_large_drawdown(monkeypatch):
    frame = make_bars_frame({"TREND": [100.0, 101.0], "SPY": [400.0, 402.0], "CASH": [1.0, 1.0]})
    _patch_bars(monkeypatch, frame)

    config = {
        "bot_id": "test-draco",
        "universe": ["TREND"],
        "market_regime_ticker": "SPY",
        "fallback_ticker": "CASH",
        "equity_history": [70.0, 100.0],  # most-recent-first: 30% drawdown from peak
    }
    result = run_draco(config)

    assert result["payload"]["circuitBreakerActive"] is True
    assert result["state"]["circuit_breaker"]["active"] is True
    assert result["state"]["circuit_breaker"]["cooldown_remaining_days"] == 20
    weights = result["payload"]["target_weights"]
    assert weights == {"CASH": pytest.approx(0.96)}


def test_run_draco_enters_and_carries_position_across_calls(monkeypatch):
    n = 300
    trend_prices = geometric_series(100.0, 0.0015, n)
    trend_prices[-1] = trend_prices[-1] * 0.85  # dip below the regression line -> entry-eligible
    frame = make_bars_frame(
        {
            "TREND": trend_prices,
            "SPY": geometric_series(400.0, 0.0005, n),  # clean uptrend -> risk_on
            "CASH": [1.0] * n,
        }
    )
    _patch_bars(monkeypatch, frame)

    config = {
        "bot_id": "test-draco",
        "universe": ["TREND"],
        "market_regime_ticker": "SPY",
        "fallback_ticker": "CASH",
        "params": {
            "minimumEntryScore": 0,
            "minimumValidTimeframes": 3,
            "minimumBelowRegressionTimeframes": 1,
            "minimumPositiveSlopeTimeframes": 1,
            "requirePositiveLongTermSlope": False,
            "minimumTargetRSquared": 0.0,
            "minimumEntryTargetUpside": 0.001,
            "maximumEntryTargetUpside": 0.9,
        },
    }

    first = run_draco(config)
    assert first["payload"]["newEntries"], "expected TREND to qualify as a new entry"
    assert "TREND" in first["payload"]["target_weights"]
    assert first["state"]["positions"]["TREND"]["entry_date"] is not None

    second = run_draco(config, state=first["state"])
    assert "TREND" in second["payload"]["target_weights"]
    assert second["payload"]["newEntries"] == []  # same trading date -> no re-scan
    assert len(second["state"]["positions"]) == 1  # still just the one position, not duplicated
