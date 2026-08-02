"""Database schema (SQLAlchemy 2.x declarative models).

Phase 1 (migration 0001): device, alpaca_credentials, strategy_config,
portfolio_allocation, signal, execution_log, device_event.

Phase 2 (migration 0002, trading_worker): order, bot_state, account_snapshot.

Phase 3 (migration 0003, updater): software_release.

Phase 4 (migration 0004, display's idle-screen rotation): position_snapshot,
bot_value_snapshot. `market_data_cache` (ARCHITECTURE.md section 7) is
still not added - the stock-candlestick view that would have needed real
exchange OHLC bars instead reuses position_snapshot's own current_price
history (the same ~60s local sampling account_snapshot already uses),
avoiding a second market-data subsystem for what's a passive status
display, not a trading terminal.

Phase 5 (migration 0005, local portfolio editing): `device.local_pin`
column, `manual_holding` table. Both exist for services/portfolio_web, a
new always-on local web page (distinct from device_agent's temporary
first-boot-only setup page) that lets the owner toggle bots on/off and add
individually-held, locked-quantity stocks - see manual_holding's own
docstring and trading_worker/manual_holdings.py.

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
    """Single-row table: this device's identity and activation state.

    `local_pin` is stored in plaintext, unlike Alpaca credentials
    (encrypted via vault.py) - deliberately different security model, not
    an oversight. It gates services/portfolio_web's local portfolio-editing
    page and must be displayable in plaintext on the device's own LCD
    (services/display) for the owner to read off and type in; it is
    generated on-device, never transmitted anywhere (not to Alpaca, not to
    Monstra), and physical possession of the device already means someone
    could just read the screen - storing it encrypted at rest would add no
    real protection while breaking the "read it off the screen" flow.
    """

    __tablename__ = "device"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    serial: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    activation_code_hash: Mapped[str | None] = mapped_column(String(128))
    activated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    owner_ref: Mapped[str | None] = mapped_column(String(128))
    disclosures_accepted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    software_version: Mapped[str | None] = mapped_column(String(32))
    local_pin: Mapped[str | None] = mapped_column(String(16))
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


class ManualHolding(Base):
    """An individual stock the owner has added directly (via
    services/portfolio_web's local page), outside of any bot's algorithm,
    with a locked target quantity.

    "Locked" means trading_worker's bots must never buy or sell this
    symbol as part of their own rebalancing - see
    trading_worker/src/trading_worker/loop.py's exclusion logic and
    trading_worker/src/trading_worker/manual_holdings.py's
    reconcile_manual_holdings(), which is the ONLY code path allowed to
    trade a locked symbol, and only ever buys up to `target_qty` - it
    never sells. Removing a row here only stops protecting that symbol
    going forward; it does not sell the shares (a deliberate, safer
    default - see manual_holdings.py's module docstring).
    """

    __tablename__ = "manual_holding"
    __table_args__ = (UniqueConstraint("symbol", name="uq_manual_holding_symbol"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    symbol: Mapped[str] = mapped_column(String(16), nullable=False, index=True)
    target_qty: Mapped[float] = mapped_column(Float, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
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


class Order(Base):
    """Every order submitted to Alpaca by trading_worker's rebalance step."""

    __tablename__ = "order"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    bot_slug: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    symbol: Mapped[str] = mapped_column(String(16), nullable=False, index=True)
    side: Mapped[str] = mapped_column(String(8), nullable=False)
    qty: Mapped[float | None] = mapped_column(Float)
    notional: Mapped[float | None] = mapped_column(Float)
    order_type: Mapped[str] = mapped_column(String(16), nullable=False, default="market")
    status: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    alpaca_order_id: Mapped[str | None] = mapped_column(String(64), index=True)
    submitted_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, index=True)
    filled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    raw_response_json: Mapped[dict[str, Any] | None] = mapped_column(JSON)


class BotState(Base):
    """Cross-run state a stateful bot (e.g. draco's open positions/regime/
    circuit-breaker) needs carried between trading_worker cycles. Not part
    of the original ARCHITECTURE.md table list — added when trading_worker
    needed somewhere to persist strategy_engine.bots.draco's `state` dict
    without a Postgres `trading.draco_state` equivalent to fall back on."""

    __tablename__ = "bot_state"
    __table_args__ = (UniqueConstraint("bot_slug", name="uq_bot_state_bot_slug"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    bot_slug: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    state_json: Mapped[dict[str, Any] | None] = mapped_column(JSON)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)


class AccountSnapshot(Base):
    """One row per trading cycle: the Alpaca account's equity/cash at that
    moment. Rolling history feeds draco's portfolio circuit breaker
    (`config["equity_history"]`) without a live DB query into the account
    on every timeframe check."""

    __tablename__ = "account_snapshot"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    ts: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, index=True)
    equity: Mapped[float] = mapped_column(Float, nullable=False)
    cash: Mapped[float] = mapped_column(Float, nullable=False)


class PositionSnapshot(Base):
    """Rolling local cache of the Alpaca account's held positions, refreshed
    on trading_worker's fast (~60s) polling cadence alongside
    `account_snapshot` (see trading_worker/main.py's
    ACCOUNT_SNAPSHOT_INTERVAL_SECONDS). Powers two display features that
    need honest, price-based data neither `order` nor `account_snapshot`
    alone provide: the idle screen's "last trade" unrealized P&L, and its
    top-movers stock candlestick view (ranked by unrealized_intraday_plpc).

    Deliberately NOT a re-attempt at the per-trade realized win/loss gap
    already documented and discarded elsewhere (see
    services/display/src/display/snapshot.py's module docstring) - this is
    *unrealized* P&L on a still-open position, computed by Alpaca itself
    from real fill data, not a proxy derived locally from notional amounts.
    """

    __tablename__ = "position_snapshot"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    ts: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, index=True)
    symbol: Mapped[str] = mapped_column(String(16), nullable=False, index=True)
    qty: Mapped[float] = mapped_column(Float, nullable=False)
    avg_entry_price: Mapped[float] = mapped_column(Float, nullable=False)
    current_price: Mapped[float] = mapped_column(Float, nullable=False)
    market_value: Mapped[float] = mapped_column(Float, nullable=False)
    unrealized_pl: Mapped[float] = mapped_column(Float, nullable=False)
    unrealized_plpc: Mapped[float] = mapped_column(Float, nullable=False)
    unrealized_intraday_plpc: Mapped[float] = mapped_column(Float, nullable=False)


class BotValueSnapshot(Base):
    """A synthetic price index tracking the bot's own chosen allocation:
    the bot's latest known target_weights (from `portfolio_allocation`,
    bot-specific and only updated when the bot actually rebalances) each
    multiplied by that symbol's current price and summed - "what would
    this bot's target basket be worth per share, weighted by its own
    target allocation" - recorded on the same fast cadence as
    `account_snapshot`. Not a dollar amount actually invested and not a
    true segregated per-bot sub-account (Alpaca positions aren't tagged by
    originating bot - ARCHITECTURE.md section 10: "no cross-bot portfolio
    netting", and `portfolio_allocation.current_weights_json` is computed
    account-wide, not per-bot, so it's deliberately NOT used here). A
    candlestick chart only needs to show relative movement, not an
    absolute dollar scale, so this index's shape is what matters - see
    trading_worker/main.py's `_record_snapshots` for the computation and
    its one real limitation (a target symbol not currently held
    contributes 0, understating the index until the bot actually acquires
    it).
    """

    __tablename__ = "bot_value_snapshot"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    ts: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, index=True)
    bot_slug: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    value: Mapped[float] = mapped_column(Float, nullable=False)


class SoftwareRelease(Base):
    """One row per release version this device has ever staged. `status`
    tracks its lifecycle: staged -> active -> (rolled_back | pruned from
    disk but the row stays as history). Exactly one row should be `active`
    at a time - enforced at the application layer (SoftwareReleaseRepository),
    not a DB constraint, since a transient window with zero active rows
    exists mid-rollback."""

    __tablename__ = "software_release"
    __table_args__ = (UniqueConstraint("version", name="uq_software_release_version"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    version: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    status: Mapped[str] = mapped_column(String(16), nullable=False, index=True)
    manifest_json: Mapped[dict[str, Any] | None] = mapped_column(JSON)
    staged_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    activated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    rolled_back_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


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
