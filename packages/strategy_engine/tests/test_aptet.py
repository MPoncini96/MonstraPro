import pytest

from strategy_engine.bots.aptet import run_aptet
from strategy_engine.bot_identity import BOT_TYPE_APTET
from tests.conftest import geometric_series, make_bars_frame


def _patch_bars(monkeypatch, frame):
    monkeypatch.setattr(
        "strategy_engine.bots.aptet.get_daily_bars",
        lambda symbols, start, end, adjusted=True: frame,
    )


def test_run_aptet_selects_holdings_from_strong_uptrend_universe(monkeypatch):
    n = 150
    frame = make_bars_frame(
        {
            "UP1": geometric_series(100.0, 0.006, n),
            "UP2": geometric_series(100.0, 0.005, n),
            "DOWN1": geometric_series(100.0, -0.004, n),
            "DOWN2": geometric_series(100.0, -0.006, n),
            "VOO": geometric_series(100.0, 0.000, n),
        }
    )
    _patch_bars(monkeypatch, frame)

    config = {
        "bot_id": "test-aptet",
        "universe": ["UP1", "UP2", "DOWN1", "DOWN2"],
        "fallback_ticker": "VOO",
        "benchmark_ticker": "VOO",
        "min_holdings": 1,
        "max_holdings": 2,
        "adaptation_speed": "aggressive",
    }
    result = run_aptet(config)

    assert result["bot_type"] == BOT_TYPE_APTET
    assert result["bot_id"] == "test-aptet"
    assert result["state"] is None
    assert result["payload"]["riskOff"] is False

    weights = result["payload"]["target_weights"]
    assert set(weights.keys()).issubset({"UP1", "UP2"})
    assert sum(weights.values()) == pytest.approx(1.0)


def test_run_aptet_holds_fallback_when_insufficient_history(monkeypatch):
    frame = make_bars_frame({"A": [100.0], "VOO": [100.0]})
    _patch_bars(monkeypatch, frame)

    config = {
        "bot_id": "test-aptet",
        "universe": ["A"],
        "fallback_ticker": "VOO",
    }
    result = run_aptet(config)

    assert result["signal"] == "HOLD"
    assert result["payload"]["target_weights"] == {"VOO": 1.0}
