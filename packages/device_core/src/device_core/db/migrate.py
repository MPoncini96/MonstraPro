"""Programmatic Alembic entry points.

Wraps alembic.command so both Database (on every open) and tests can drive
migrations without shelling out. The same migrations/ tree is also
CLI-runnable directly (`alembic upgrade head` from packages/device_core) -
see alembic.ini and migrations/env.py for how the two paths agree on which
database URL to use.
"""

from __future__ import annotations

from pathlib import Path

from alembic import command
from alembic.config import Config as AlembicConfig
from alembic.runtime.migration import MigrationContext
from alembic.script import ScriptDirectory
from sqlalchemy import create_engine

_PACKAGE_ROOT = Path(__file__).resolve().parents[3]  # packages/device_core
_SCRIPT_LOCATION = _PACKAGE_ROOT / "src" / "device_core" / "db" / "migrations"


def _alembic_config(db_url: str) -> AlembicConfig:
    cfg = AlembicConfig(str(_PACKAGE_ROOT / "alembic.ini"))
    cfg.set_main_option("script_location", str(_SCRIPT_LOCATION))
    cfg.set_main_option("sqlalchemy.url", db_url)
    return cfg


def upgrade_to_head(db_url: str) -> None:
    command.upgrade(_alembic_config(db_url), "head")


def downgrade_to_base(db_url: str) -> None:
    command.downgrade(_alembic_config(db_url), "base")


def head_revision() -> str | None:
    script = ScriptDirectory(str(_SCRIPT_LOCATION))
    return script.get_current_head()


def current_revision(db_url: str) -> str | None:
    """The revision actually applied to db_url, independent of alembic.ini."""
    engine = create_engine(db_url)
    try:
        with engine.connect() as connection:
            context = MigrationContext.configure(connection)
            return context.get_current_revision()
    finally:
        engine.dispose()
