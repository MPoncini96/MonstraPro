from strategy_engine.bot_identity import BOT_TYPE_ALPHA1, BOT_TYPE_APTET, BOT_TYPE_DRACO


def test_bot_type_constants_are_distinct_strings():
    values = {BOT_TYPE_ALPHA1, BOT_TYPE_APTET, BOT_TYPE_DRACO}
    assert values == {"alpha1", "aptet", "draco"}
    assert len(values) == 3
