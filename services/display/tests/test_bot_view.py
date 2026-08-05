from display.bot_view import build_bot_view


def test_unconfigured_bot_has_no_display_name_signal_or_weights(core):
    view = build_bot_view(core, "force")

    assert view.bot_slug == "force"
    assert view.display_name is None
    assert view.latest_signal is None
    assert view.target_weights == {}
    assert view.status == "IDLE"
    assert view.latest_action is None


def test_includes_display_name_algorithm_family_and_latest_signal(core):
    core.strategies.upsert(bot_slug="force", bot_type="force", display_name="Force")
    core.signals.store(bot_id="force", bot_type="alpha1", signal="REBALANCE", note="top=AAPL")

    view = build_bot_view(core, "force")

    assert view.display_name == "Force"
    assert view.algorithm_family == "Force"
    assert view.latest_signal == "REBALANCE"


def test_signal_lookup_uses_engine_bot_type_not_bot_slug(core):
    """Regression test: for a monstra.pro-synced row, bot_slug is a
    per-instance identity (e.g. "vectura_draco") separate from bot_type
    (the engine family, "draco") - the signal lookup must use the engine's
    real bot_type ("draco"), not the raw bot_slug string, or a synced bot's
    signal is never found."""
    core.strategies.upsert(bot_slug="vectura_draco", bot_type="draco", source="monstra.pro")
    core.signals.store(bot_id="vectura_draco", bot_type="draco", signal="HOLD")

    view = build_bot_view(core, "vectura_draco")

    assert view.latest_signal == "HOLD"
    assert view.algorithm_family == "Draco"
    assert view.status == "WAITING"


def test_target_weights_come_from_latest_allocation(core):
    core.strategies.upsert(bot_slug="force")
    core.allocations.replace(bot_slug="force", target_weights={"AAPL": 0.6, "MSFT": 0.4}, current_weights={})

    view = build_bot_view(core, "force")

    assert view.target_weights == {"AAPL": 0.6, "MSFT": 0.4}


def test_latest_action_is_the_biggest_change_since_the_prior_allocation(core):
    core.strategies.upsert(bot_slug="force")
    core.signals.store(bot_id="force", bot_type="alpha1", signal="REBALANCE")
    core.allocations.replace(bot_slug="force", target_weights={"AAPL": 1.0}, current_weights={})
    core.allocations.replace(bot_slug="force", target_weights={"AAPL": 0.5, "MSFT": 0.5}, current_weights={})

    view = build_bot_view(core, "force")

    assert view.latest_action.side == "buy"
    assert view.latest_action.symbol == "MSFT"
    assert view.status == "BUYING"


def test_latest_action_status_is_completed_when_the_account_already_holds_the_symbol(core):
    core.strategies.upsert(bot_slug="force")
    core.allocations.replace(bot_slug="force", target_weights={"AAPL": 1.0}, current_weights={})
    core.allocations.replace(bot_slug="force", target_weights={"AAPL": 0.5, "MSFT": 0.5}, current_weights={})
    core.positions.record(
        symbol="MSFT",
        qty=5,
        avg_entry_price=100.0,
        current_price=101.0,
        market_value=505.0,
        unrealized_pl=5.0,
        unrealized_plpc=0.01,
        unrealized_intraday_plpc=0.01,
    )

    view = build_bot_view(core, "force")

    assert view.latest_action.status == "Completed"


def test_latest_action_status_is_pending_when_the_account_has_not_caught_up(core):
    core.strategies.upsert(bot_slug="force")
    core.allocations.replace(bot_slug="force", target_weights={"AAPL": 1.0}, current_weights={})
    core.allocations.replace(bot_slug="force", target_weights={"AAPL": 0.5, "MSFT": 0.5}, current_weights={})

    view = build_bot_view(core, "force")

    assert view.latest_action.status == "Pending"


def test_first_ever_allocation_is_reported_as_a_buy(core):
    core.strategies.upsert(bot_slug="force")
    core.allocations.replace(bot_slug="force", target_weights={"AAPL": 1.0}, current_weights={})

    view = build_bot_view(core, "force")

    assert view.latest_action.side == "buy"
    assert view.latest_action.symbol == "AAPL"


def test_no_latest_action_when_the_allocation_is_unchanged(core):
    core.strategies.upsert(bot_slug="force")
    core.allocations.replace(bot_slug="force", target_weights={"AAPL": 1.0}, current_weights={})
    core.allocations.replace(bot_slug="force", target_weights={"AAPL": 1.0}, current_weights={})

    view = build_bot_view(core, "force")

    assert view.latest_action is None


def test_status_is_idle_with_no_signal_yet(core):
    core.strategies.upsert(bot_slug="force")

    view = build_bot_view(core, "force")

    assert view.status == "IDLE"


def test_status_is_waiting_on_hold_signal(core):
    core.strategies.upsert(bot_slug="force", bot_type="force")
    core.signals.store(bot_id="force", bot_type="alpha1", signal="HOLD")

    view = build_bot_view(core, "force")

    assert view.status == "WAITING"
