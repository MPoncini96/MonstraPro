import sqlalchemy as sa

from device_core.db import migrate

_EXPECTED_TABLES = {
    "device",
    "alpaca_credentials",
    "strategy_config",
    "portfolio_allocation",
    "signal",
    "execution_log",
    "device_event",
    "order",
    "bot_state",
    "account_snapshot",
    "software_release",
    "position_snapshot",
    "bot_value_snapshot",
    "manual_holding",
}


def _table_names(db_url: str) -> set[str]:
    engine = sa.create_engine(db_url)
    try:
        return set(sa.inspect(engine).get_table_names())
    finally:
        engine.dispose()


def test_upgrade_to_head_creates_all_tables(tmp_path):
    db_url = f"sqlite:///{(tmp_path / 'migrate.db').as_posix()}"

    migrate.upgrade_to_head(db_url)

    tables = _table_names(db_url)
    assert _EXPECTED_TABLES <= tables


def test_current_revision_matches_head_after_upgrade(tmp_path):
    db_url = f"sqlite:///{(tmp_path / 'migrate.db').as_posix()}"

    migrate.upgrade_to_head(db_url)

    assert migrate.current_revision(db_url) == migrate.head_revision()


def test_downgrade_to_base_drops_all_tables(tmp_path):
    db_url = f"sqlite:///{(tmp_path / 'migrate.db').as_posix()}"
    migrate.upgrade_to_head(db_url)

    migrate.downgrade_to_base(db_url)

    tables = _table_names(db_url)
    assert not (_EXPECTED_TABLES & tables)
    assert migrate.current_revision(db_url) is None


def test_upgrade_downgrade_upgrade_cycle(tmp_path):
    db_url = f"sqlite:///{(tmp_path / 'migrate.db').as_posix()}"

    migrate.upgrade_to_head(db_url)
    migrate.downgrade_to_base(db_url)
    migrate.upgrade_to_head(db_url)

    tables = _table_names(db_url)
    assert _EXPECTED_TABLES <= tables
    assert migrate.current_revision(db_url) == migrate.head_revision()
