from display.bot_view import build_bot_view


def test_unconfigured_bot_has_no_display_name_signal_or_candles(core):
    view = build_bot_view(core, "force")

    assert view.bot_slug == "force"
    assert view.display_name is None
    assert view.latest_signal is None
    assert view.candles == []


def test_includes_display_name_and_latest_signal(core):
    core.strategies.upsert(bot_slug="force", display_name="Force")
    core.signals.store(bot_id="force", bot_type="alpha1", signal="REBALANCE", note="top=AAPL")

    view = build_bot_view(core, "force")

    assert view.display_name == "Force"
    assert view.latest_signal == "REBALANCE"


def test_candles_are_built_from_bot_value_history(core):
    core.bot_values.record(bot_slug="force", value=100.0)
    core.bot_values.record(bot_slug="force", value=110.0)

    view = build_bot_view(core, "force")

    assert len(view.candles) >= 1
    assert view.candles[-1].close == 110.0


def test_other_bots_values_do_not_leak_in(core):
    core.bot_values.record(bot_slug="aptet", value=999.0)

    view = build_bot_view(core, "force")

    assert view.candles == []
