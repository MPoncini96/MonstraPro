"""Database schema (SQLAlchemy 2.x declarative models).

Phase 1 scope only: device, alpaca_credentials, strategy_config,
portfolio_allocation, signal, execution_log, device_event. `orders`,
`market_data_cache`, and `software_release` belong to trading_worker and
updater respectively and are added as later migrations when those phases
start - see ARCHITECTURE.md section 7.

Schema is created/evolved exclusively through Alembic migrations
(db/migrations/versions/) - this module defines the mapped classes that
migration 0001 mirrors by hand; nothing here calls create_all() in
production. See db/migrate.py and db/session.py.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from sqlalchemy import (
    DateTime,
    Boolean,
    Float,
    Integer,
    JSON,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


def utcnow() -> datetime:
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
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)


class AlpacaCredentials(Base):
    """Encrypted Alpaca API key/secret, one row per mode (paper/live)."""

    __tablename__ = "alpaca_credentials"
    __table_args__ = (UniqueConstraint("mode", name="uq_alpaca_credentials_mode"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    mode: Mapped[str] = mapped_column(String(16), nullable=False, index=True)
    api_key_encrypted: Mapped[str] = mapped_column(Text, nullable=False)
    api_secret_encrypted: Mapped[str] = mapped_column(Text, nullable=False)
    base_url: Mapped[str] = mapped_column(String(255), nullable=False)
    connected_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)


class StrategyConfig(Base):
    """The owner's configured strategy/strategies, one row per bot_slug."""

    __tablename__ = "strategy_config"
    __table_args__ = (UniqueConstraint("bot_slug", name="uq_strategy_config_bot_slug"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    bot_slug: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    display_name: Mapped[str | None] = mapped_column(String(128))
    params_json: Mapped[dict[str, Any] | None] = mapped_column(JSON)
    target_allocation_json: Mapped[dict[str, Any] | None] = mapped_column(JSON)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    source: Mapped[str] = mapped_column(String(32), nullable=False, default="local")
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)


class PortfolioAllocation(Base):
    """Historical target vs. current weights per bot, timestamped."""

    __tablename__ = "portfolio_allocation"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    bot_slug: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    ts: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, index=True)
    target_weights_json: Mapped[dict[str, Any] | None] = mapped_column(JSON)
    current_weights_json: Mapped[dict[str, Any] | None] = mapped_column(JSON)


class Signal(Base):
    """Signal history, one row per strategy run. Mirrors Monstra-Worker's
    signal dict shape so ported bot code doesn't need reshaping."""

    __tablename__ = "signal"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    bot_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    bot_type: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    ts: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, index=True)
    signal: Mapped[str] = mapped_column(String(32), nullable=False)
    note: Mapped[str | None] = mapped_column(Text)
    payload_json: Mapped[dict[str, Any] | None] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class ExecutionLog(Base):
    """Structured application log, persisted independent of journald retention."""

    __tablename__ = "execution_log"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    ts: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, index=True)
    level: Mapped[str] = mapped_column(String(16), nullable=False)
    component: Mapped[str] = mapped_column(String(64), nullable=False)
    message: Mapped[str] = mapped_column(Text, nullable=False)
    context_json: Mapped[dict[str, Any] | None] = mapped_column(JSON)


class DeviceEvent(Base):
    """Append-only local event queue. Consumers poll list_unconsumed() and
    ack with mark_consumed() - events preserve publish order and stay
    unconsumed until explicitly acknowledged."""

    __tablename__ = "device_event"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    ts: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, index=True)
    type: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    severity: Mapped[str] = mapped_column(String(16), nullable=False, default="info")
    payload_json: Mapped[dict[str, Any] | None] = mapped_column(JSON)
    consumed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), index=True)
    consumed_by: Mapped[str | None] = mapped_column(String(64))
