import math

import pytest

from strategy_engine.bots import draco_math as dm


def _geometric(start: float, daily_return: float, n: int) -> list[float]:
    return [start * (1.0 + daily_return) ** t for t in range(n)]


def test_fit_log_linear_regression_recovers_known_slope():
    daily_return = 0.001
    prices = _geometric(100.0, daily_return, 60)
    fit = dm.fit_log_linear_regression(prices)
    assert fit is not None
    slope, intercept, index, log_prices = fit
    assert slope == pytest.approx(math.log(1.0 + daily_return), abs=1e-6)


def test_fit_log_linear_regression_rejects_short_or_invalid_series():
    assert dm.fit_log_linear_regression([1.0, 2.0]) is None  # below MINIMUM_WINDOW_LENGTH
    assert dm.fit_log_linear_regression([1.0, -2.0, 3.0]) is None  # non-positive value
    assert dm.fit_log_linear_regression([1.0, float("nan"), 3.0]) is None


def test_compute_timeframe_metrics_perfect_uptrend_has_high_r_squared():
    prices = _geometric(100.0, 0.002, 30)
    metrics = dm.compute_timeframe_metrics("1M", 21, prices)
    assert metrics is not None
    assert metrics.r_squared == pytest.approx(1.0, abs=1e-6)
    assert metrics.slope > 0
    assert metrics.annualized_slope > 0


def test_compute_timeframe_metrics_insufficient_history_returns_none():
    assert dm.compute_timeframe_metrics("1M", 21, [100.0] * 10) is None


def test_compute_all_timeframe_metrics_only_includes_satisfiable_lookbacks():
    prices = _geometric(100.0, 0.001, 100)
    metrics = dm.compute_all_timeframe_metrics(prices)
    assert set(metrics.keys()) == {"1M", "3M"}  # only lookbacks <= 100 (21, 63)


def test_evaluate_entry_requirements_true_for_dip_below_clean_uptrend():
    # Needs every configured lookback (up to 5Y=1260) satisfied to hit
    # minimum_valid_timeframes=6 with the default requirements, plus a
    # genuine (not floating-point-noise-sized) dip below the regression
    # line so minimum_below_line_timeframes is unambiguously satisfied.
    prices = _geometric(50.0, 0.0015, dm.LOOKBACKS["5Y"] + 5)
    prices[-1] *= 0.85
    metrics = dm.compute_all_timeframe_metrics(prices)
    assert len(metrics) == len(dm.LOOKBACKS)
    total_score = dm.compute_total_score(metrics)
    current_price = prices[-1]
    assert dm.evaluate_entry_requirements(metrics, total_score, current_price) is True


def test_evaluate_entry_requirements_false_for_monotonic_decline():
    prices = _geometric(200.0, -0.0015, dm.LOOKBACKS["5Y"] + 5)
    metrics = dm.compute_all_timeframe_metrics(prices)
    total_score = dm.compute_total_score(metrics)
    current_price = prices[-1]
    assert dm.evaluate_entry_requirements(metrics, total_score, current_price) is False


def test_evaluate_entry_requirements_false_when_too_few_timeframes():
    prices = _geometric(100.0, 0.001, 25)  # only 1M lookback satisfiable
    metrics = dm.compute_all_timeframe_metrics(prices)
    total_score = dm.compute_total_score(metrics)
    assert dm.evaluate_entry_requirements(metrics, total_score, prices[-1]) is False


def test_select_locked_target_requires_price_below_target_line():
    prices = _geometric(50.0, 0.0015, dm.LOOKBACKS["2Y"] + 5)
    metrics = dm.compute_all_timeframe_metrics(prices)
    # Current price is exactly on the regression line's endpoint by construction
    # (pure geometric series fits its own regression perfectly), so there is no
    # "upside" left and no target should be selected.
    target = dm.select_locked_target(metrics, prices[-1])
    assert target is None


def test_select_locked_target_and_project_locked_target_roundtrip():
    # A price that dipped below where a clean uptrend "should" be has upside
    # versus the fitted line.
    prices = _geometric(50.0, 0.0015, dm.LOOKBACKS["1Y"] + 5)
    dipped_price = prices[-1] * 0.85
    prices[-1] = dipped_price
    metrics = dm.compute_all_timeframe_metrics(prices)
    target = dm.select_locked_target(metrics, dipped_price)
    assert target is not None
    assert target.entry_upside > 0

    projected_at_entry = dm.project_locked_target(target, 0)
    assert projected_at_entry == pytest.approx(target.entry_target_price, rel=1e-6)

    projected_later = dm.project_locked_target(target, 30)
    assert projected_later > projected_at_entry  # regression line keeps climbing


def test_deviation_and_slope_point_buckets_are_monotonic():
    z_scores = [-3.0, -2.5, -2.0, -1.5, -1.0, -0.5, 0.0, 1.0]
    points = [dm.deviation_points(z) for z in z_scores]
    assert points == sorted(points, reverse=True)

    slopes = [-0.1, 0.0, 0.03, 0.08, 0.15, 0.25, 0.40]
    slope_points = [dm.annualized_slope_points(s) for s in slopes]
    assert slope_points == sorted(slope_points)
