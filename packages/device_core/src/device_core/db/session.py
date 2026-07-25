"""SQLite engine + session management.

No domain methods live here - that's what the repositories in
device_core.repositories are for. This class owns exactly: the engine,
its SQLite pragmas (foreign keys, WAL, busy timeout), running migrations
up to head on open, and handing out commit/rollback-safe sessions.
"""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager

from sqlalchemy import create_engine, event
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker

from device_core.config import Config
from device_core.db import migrate


def _register_pragmas(engine: Engine) -> None:
    @event.listens_for(engine, "connect")
    def _set_sqlite_pragmas(dbapi_connection, _connection_record) -> None:  # noqa: ANN001
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA foreign_keys = ON")
        cursor.execute("PRAGMA journal_mode = WAL")
        cursor.execute("PRAGMA busy_timeout = 5000")
        cursor.close()


class Database:
    """Owns the SQLite engine/session factory for one device's config."""

    def __init__(self, config: Config, *, echo: bool = False, run_migrations: bool = True) -> None:
        self.config = config
        self.engine = create_engine(config.sqlite_url, echo=echo, future=True)
        _register_pragmas(self.engine)
        if run_migrations:
            migrate.upgrade_to_head(config.sqlite_url)
        self._session_factory = sessionmaker(bind=self.engine, expire_on_commit=False, future=True)

    @contextmanager
    def session(self) -> Iterator[Session]:
        session = self._session_factory()
        try:
            yield session
            session.commit()
        except Exception:
            session.rollback()
            raise
        finally:
            session.close()

    def close(self) -> None:
        self.engine.dispose()
