"""Alembic environment.

Resolves the target database URL from, in order: the MONSTRAPRO_SQLITE_URL
env var (used by the manual `alembic upgrade head` CLI verification pass so
it never touches a real device DB by accident), then whatever
sqlalchemy.url is already set to on the Config object - which is what
device_core.db.migrate sets programmatically before invoking Alembic
in-process. Falls back to alembic.ini's static value only if neither
applies.
"""

from __future__ import annotations

import logging
import os
from logging.config import fileConfig

from alembic import context
from sqlalchemy import engine_from_config, pool

from device_core.db.models import Base

config = context.config

# Only let Alembic configure Python logging when nothing else has yet (a
# bare `alembic` CLI run). When Alembic runs in-process - which is every
# Database()/DeviceCore.load() call, since that runs migrations on open -
# device_core.logging.configure_logging() has already installed the
# application's own root handler; fileConfig() would silently replace it
# (its [logger_root] section assigns root's handlers unconditionally),
# so skip it in that case rather than fighting the app for the root logger.
if config.config_file_name is not None and not logging.getLogger().handlers:
    fileConfig(config.config_file_name)

target_metadata = Base.metadata

_db_url = os.environ.get("MONSTRAPRO_SQLITE_URL") or config.get_main_option("sqlalchemy.url")
config.set_main_option("sqlalchemy.url", _db_url)


def run_migrations_offline() -> None:
    context.configure(
        url=_db_url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    connectable = engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )
    with connectable.connect() as connection:
        context.configure(connection=connection, target_metadata=target_metadata)
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
