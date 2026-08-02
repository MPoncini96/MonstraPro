import pytest

from strategy_engine.bots.alpha1 import run_alpha1
from strategy_engine.bot_identity import BOT_TYPE_ALPHA1
from tests.conftest import geometric_series, make_bars_frame


def _patch_bars(monkeypatch, frame):
    monkeypatch.setattr(
        "strategy_engine.bots.alpha1.get_daily_bars",
        lambda symbols, start, end, adjusted=True: frame,
    )


def test_run_alpha1_selects_top_n_by_trailing_growth(monkeypatch):
    n = 40
    frame = make_bars_frame(
        {
            "FAST": geometric_series(100.0, 0.010, n),
            "MED": geometric_series(100.0, 0.004, n),
            "SLOW": geometric_series(100.0, 0.001, n),
            "FLAT": geometric_series(100.0, 0.000, n),
            "CASH": geometric_series(100.0, 0.000, n),
        }
    )
    _patch_bars(monkeypatch, frame)

    config = {
        "bot_id": "test-force",
        "universe": ["FAST", "MED", "SLOW", "FLAT"],
        "cash_equivalent": "CASH",
        "top_n": 2,
        "lookback_days": 14,
        "rank_weights": [0.6, 0.4],
    }
    result = run_alpha1(config)

    assert result["bot_type"] == BOT_TYPE_ALPHA1
    assert result["bot_id"] == "test-force"
    assert result["signal"] == "REBALANCE"
    assert result["state"] is None

    weights = result["payload"]["target_weights"]
    assert set(weights.keys()) == {"FAST", "MED"}
    assert weights["FAST"] == pytest.approx(0.6)
    assert weights["MED"] == pytest.approx(0.4)
    assert sum(weights.values()) == pytest.approx(1.0)


def test_run_alpha1_kill_switch_falls_back_to_cash_when_top_return_negative(monkeypatch):
    n = 40
    frame = make_bars_frame(
        {
            "A": geometric_series(100.0, -0.01, n),
            "B": geometric_series(100.0, -0.02, n),
            "CASH": geometric_series(100.0, 0.000, n),
        }
    )
    _patch_bars(monkeypatch, frame)

    config = {
        "bot_id": "test-force",
        "universe": ["A", "B"],
        "cash_equivalent": "CASH",
        "top_n": 1,
        "lookback_days": 14,
    }
    result = run_alpha1(config)

    assert result["payload"]["risk_off"] is True
    assert result["payload"]["target_weights"] == {"CASH": 1.0}


def test_run_alpha1_holds_cash_when_insufficient_history(monkeypatch):
    frame = make_bars_frame({"A": [100.0], "CASH": [100.0]})
    _patch_bars(monkeypatch, frame)

    config = {
        "bot_id": "test-force",
        "universe": ["A"],
        "cash_equivalent": "CASH",
        "lookback_days": 14,
    }
    result = run_alpha1(config)

    assert result["signal"] == "HOLD"
    assert result["payload"]["target_weights"] == {"CASH": 1.0}
