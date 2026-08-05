from display.bot_view import build_bot_view


def test_unconfigured_bot_has_no_display_name_signal_or_weights(core):
    view = build_bot_view(core, "force")

    assert view.bot_slug == "force"
    assert view.display_name is None
    assert view.latest_signal is None
    assert view.target_weights == {}
    assert view.recent_orders == []


def test_includes_display_name_and_latest_signal(core):
    core.strategies.upsert(bot_slug="force", display_name="Force")
    core.signals.store(bot_id="force", bot_type="alpha1", signal="REBALANCE", note="top=AAPL")

    view = build_bot_view(core, "force")

    assert view.display_name == "Force"
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


def test_target_weights_come_from_latest_allocation(core):
    core.strategies.upsert(bot_slug="force")
    core.allocations.replace(bot_slug="force", target_weights={"AAPL": 0.6, "MSFT": 0.4}, current_weights={})

    view = build_bot_view(core, "force")

    assert view.target_weights == {"AAPL": 0.6, "MSFT": 0.4}


def test_recent_orders_are_the_devices_overall_last_orders(core):
    """Not filtered to this bot - per-bot order attribution is lost once
    trades are netted (see bot_view.py's module docstring)."""
    core.orders.record(bot_slug="_portfolio", symbol="AAPL", side="buy", notional=100.0, status="accepted")
    core.orders.record(bot_slug="_portfolio", symbol="MSFT", side="sell", notional=50.0, status="accepted")

    view = build_bot_view(core, "force")

    assert [o["symbol"] for o in view.recent_orders] == ["MSFT", "AAPL"]  # newest first


def test_recent_orders_respects_the_limit_of_eight(core):
    for i in range(10):
        core.orders.record(bot_slug="_portfolio", symbol=f"SYM{i}", side="buy", notional=10.0, status="accepted")

    view = build_bot_view(core, "force")

    assert len(view.recent_orders) == 8
