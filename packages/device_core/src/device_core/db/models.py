"""Database schema (SQLAlchemy models).

Table names and purpose follow ARCHITECTURE.md section 7 exactly, with one
deliberate deviation: the orders table is named ``orders`` rather than
``order``, since ORDER is a reserved SQL keyword in most dialects
(including the Postgres this may migrate to later) and there's no upside
to fighting that.

V1 creates this schema via ``device_core.db.engine.init_schema``
(``Base.metadata.create_all``) rather than Alembic migrations - the schema
doesn't need to evolve in the field until the updater service exists.
Because everything here is already a SQLAlchemy declarative mapping,
wiring Alembic later (autogenerate against ``Base.metadata``) is a
mechanical follow-up, not a rewrite.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from sqlalchemy import (
    Boolean,
    DateTime,
    Float,
    Integer,
    JSON,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class Base(DeclarativeBase):
    pass


class Device(Base):
    """Single-row table: this device's identity and activation state."""

    __tablename__ = "device"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    serial: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    activation_code_hash: Mapped[str | None] = mapped_column(String(128))
    activated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    owner_ref: Mapped[str | None] = mapped_column(String(128))
    disclosures_accepted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    software_version: Mapped[str | None] = mapped_column(String(32))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow, onupdate=_utcnow)


class AlpacaCredentials(Base):
    """Encrypted Alpaca API key/secret. Values are Fernet tokens, not plaintext."""

    __tablename__ = "alpaca_credentials"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    api_key_encrypted: Mapped[str] = mapped_column(Text, nullable=False)
    api_secret_encrypted: Mapped[str] = mapped_column(Text, nullable=False)
    base_url: Mapped[str] = mapped_column(String(255), nullable=False)
    mode: Mapped[str] = mapped_column(String(16), nullable=False, default="paper")
    connected_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow, onupdate=_utcnow)


class StrategyConfig(Base):
    """The owner's configured strategy/strategies (one row per bot_slug)."""

    __tablename__ = "strategy_config"
    __table_args__ = (UniqueConstraint("bot_slug", name="uq_strategy_config_bot_slug"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    bot_slug: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    display_name: Mapped[str | None] = mapped_column(String(128))
    params_json: Mapped[dict[str, Any] | None] = mapped_column(JSON)
    target_allocation_json: Mapped[dict[str, Any] | None] = mapped_column(JSON)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    source: Mapped[str] = mapped_column(String(32), nullable=False, default="local")
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow, onupdate=_utcnow)


class PortfolioAllocation(Base):
    """Historical target vs. current weights per bot, timestamped."""

    __tablename__ = "portfolio_allocation"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    bot_slug: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    ts: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow, index=True)
    target_weights_json: Mapped[dict[str, Any] | None] = mapped_column(JSON)
    current_weights_json: Mapped[dict[str, Any] | None] = mapped_column(JSON)


class Signal(Base):
    """Signal history, one row per strategy run. Shape mirrors Monstra-Worker's
    signal dict so ported bot code doesn't need reshaping."""

    __tablename__ = "signal"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    bot_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    bot_type: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    ts: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow, index=True)
    signal: Mapped[str] = mapped_column(String(32), nullable=False)
    note: Mapped[str | None] = mapped_column(Text)
    payload_json: Mapped[dict[str, Any] | None] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)


class Order(Base):
    """Every order submitted to Alpaca. Table name is ``orders`` - see module docstring."""

    __tablename__ = "orders"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    alpaca_order_id: Mapped[str | None] = mapped_column(String(64), index=True)
    bot_slug: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    symbol: Mapped[str] = mapped_column(String(16), nullable=False)
    side: Mapped[str] = mapped_column(String(8), nullable=False)
    qty: Mapped[float | None] = mapped_column(Float)
    notional: Mapped[float | None] = mapped_column(Float)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="pending")
    submitted_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)
    filled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    raw_response_json: Mapped[dict[str, Any] | None] = mapped_column(JSON)


class ExecutionLog(Base):
    """Structured application log, persisted independent of journald retention."""

    __tablename__ = "execution_log"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    ts: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow, index=True)
    level: Mapped[str] = mapped_column(String(16), nullable=False)
    component: Mapped[str] = mapped_column(String(64), nullable=False)
    message: Mapped[str] = mapped_column(Text, nullable=False)
    context_json: Mapped[dict[str, Any] | None] = mapped_column(JSON)


class MarketDataCache(Base):
    """Cached OHLCV bars, so a cycle isn't fully dependent on live connectivity."""

    __tablename__ = "market_data_cache"
    __table_args__ = (
        UniqueConstraint("symbol", "ts", "source", name="uq_market_data_symbol_ts_source"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    symbol: Mapped[str] = mapped_column(String(16), nullable=False, index=True)
    ts: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, index=True)
    open: Mapped[float | None] = mapped_column(Float)
    high: Mapped[float | None] = mapped_column(Float)
    low: Mapped[float | None] = mapped_column(Float)
    close: Mapped[float | None] = mapped_column(Float)
    volume: Mapped[float | None] = mapped_column(Float)
    source: Mapped[str] = mapped_column(String(32), nullable=False)


class SoftwareRelease(Base):
    """Installed/staged release versions, used by the updater service."""

    __tablename__ = "software_release"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    version: Mapped[str] = mapped_column(String(32), nullable=False, unique=True)
    applied_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="staged")
    manifest_json: Mapped[dict[str, Any] | None] = mapped_column(JSON)


class DeviceEvent(Base):
    """Append-only local event log - the pub/sub channel `display` polls."""

    __tablename__ = "device_event"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    ts: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow, index=True)
    type: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    payload_json: Mapped[dict[str, Any] | None] = mapped_column(JSON)
