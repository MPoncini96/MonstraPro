import pytest

from trading_worker.rebalance import compute_order_plan, exclude_locked_symbols


def test_new_positions_are_all_buys():
    plan = compute_order_plan(
        target_weights={"AAPL": 0.6, "MSFT": 0.4},
        current_position_values={},
        account_equity=1000.0,
    )
    assert {item.symbol: item.notional for item in plan} == {"AAPL": 600.0, "MSFT": 400.0}
    assert all(item.side == "buy" for item in plan)


def test_symbol_dropped_from_target_is_fully_sold():
    plan = compute_order_plan(
        target_weights={"AAPL": 1.0},
        current_position_values={"AAPL": 500.0, "MSFT": 300.0},
        account_equity=1000.0,
    )
    sells = [item for item in plan if item.side == "sell"]
    assert len(sells) == 1
    assert sells[0].symbol == "MSFT"
    assert sells[0].notional == pytest.approx(300.0)


def test_sells_ordered_before_buys():
    plan = compute_order_plan(
        target_weights={"AAPL": 1.0},
        current_position_values={"MSFT": 500.0},
        account_equity=1000.0,
    )
    assert [item.side for item in plan] == ["sell", "buy"]


def test_dust_diffs_below_threshold_are_dropped():
    plan = compute_order_plan(
        target_weights={"AAPL": 0.5001},
        current_position_values={"AAPL": 500.0},
        account_equity=1000.0,
        min_trade_dollars=1.0,
    )
    assert plan == []


def test_zero_or_negative_equity_returns_no_orders():
    assert compute_order_plan(target_weights={"AAPL": 1.0}, current_position_values={}, account_equity=0.0) == []
    assert compute_order_plan(target_weights={"AAPL": 1.0}, current_position_values={}, account_equity=-100.0) == []


def test_already_at_target_produces_no_orders():
    plan = compute_order_plan(
        target_weights={"AAPL": 0.5, "MSFT": 0.5},
        current_position_values={"AAPL": 500.0, "MSFT": 500.0},
        account_equity=1000.0,
    )
    assert plan == []


def test_locked_position_would_otherwise_be_sold_without_exclusion():
    """Regression guard for the actual bug this exclusion fixes: a locked
    manual holding with no corresponding bot target weight looks, to
    compute_order_plan alone, exactly like "a position the bot should
    fully exit" - see test_symbol_dropped_from_target_is_fully_sold above.
    exclude_locked_symbols is what prevents that in loop.py's real flow."""
    plan = compute_order_plan(
        target_weights={"AAPL": 1.0},
        current_position_values={"AAPL": 500.0, "TSLA": 300.0},  # TSLA is a locked holding here
        account_equity=1000.0,
    )
    assert any(item.symbol == "TSLA" and item.side == "sell" for item in plan)


class TestExcludeLockedSymbols:
    def test_no_locked_symbols_is_unchanged(self):
        weights = {"AAPL": 0.6, "MSFT": 0.4}
        assert exclude_locked_symbols(weights, set()) == weights

    def test_drops_locked_symbol_and_renormalizes_remainder(self):
        result = exclude_locked_symbols({"AAPL": 0.5, "MSFT": 0.3, "TSLA": 0.2}, {"TSLA"})
        assert "TSLA" not in result
        assert result["AAPL"] == pytest.approx(0.5 / 0.8)
        assert result["MSFT"] == pytest.approx(0.3 / 0.8)
        assert sum(result.values()) == pytest.approx(1.0)

    def test_all_targets_locked_returns_empty(self):
        assert exclude_locked_symbols({"AAPL": 1.0}, {"AAPL"}) == {}

    def test_locked_symbol_not_in_targets_has_no_effect(self):
        weights = {"AAPL": 1.0}
        assert exclude_locked_symbols(weights, {"TSLA"}) == weights
