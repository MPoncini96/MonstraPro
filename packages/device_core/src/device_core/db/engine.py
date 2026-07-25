"""SQLAlchemy engine factory and schema initialization."""

from __future__ import annotations

from sqlalchemy import create_engine, event
from sqlalchemy.engine import Engine

from device_core.config import Config
from device_core.db.models import Base


def build_sqlite_url(config: Config) -> str:
    config.data_dir.mkdir(parents=True, exist_ok=True)
    return f"sqlite:///{config.db_path.as_posix()}"


def create_engine_from_config(config: Config, *, echo: bool = False) -> Engine:
    engine = create_engine(build_sqlite_url(config), echo=echo, future=True)

    @event.listens_for(engine, "connect")
    def _set_sqlite_pragmas(dbapi_connection, _connection_record) -> None:  # noqa: ANN001
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA foreign_keys = ON")
        cursor.execute("PRAGMA journal_mode = WAL")
        cursor.close()

    return engine


def init_schema(engine: Engine) -> None:
    """Create any tables that don't exist yet.

    V1 uses ``create_all`` rather than Alembic migrations - see the
    device_core/db/models.py module docstring for why, and
    ARCHITECTURE.md section 7 for the schema this creates.
    """
    Base.metadata.create_all(engine)
