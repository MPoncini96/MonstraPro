"""Database facade.

Opens the engine, owns sessions, and exposes the narrow set of operations
other services need (signals, orders, execution log, encrypted Alpaca
credentials, strategy config, portfolio allocation, market data cache,
software releases). Keeping these as methods on one object - rather than
scattering raw SQLAlchemy session use through trading_worker/display/
updater - keeps the schema an implementation detail those services don't
need to know about.

device_core.events.EventBus wraps the same Database for device_event
reads/writes rather than duplicating session handling.
"""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from datetime import datetime, timezone
from typing import Any

from sqlalchemy.orm import Session, sessionmaker

from device_core.config import Config
from device_core.crypto import Encryptor, get_encryptor
from device_core.db.engine import create_engine_from_config, init_schema
from device_core.db.models import (
    AlpacaCredentials,
    ExecutionLog,
    MarketDataCache,
    Order,
    PortfolioAllocation,
    Signal,
    SoftwareRelease,
    StrategyConfig,
)


def _row_to_dict(row: Any) -> dict[str, Any]:
    return {column.name: getattr(row, column.name) for column in row.__table__.columns}


class Database:
    """Owns the SQLite engine/session factory for one device."""

    def __init__(self, config: Config, *, echo: bool = False) -> None:
        self.config = config
        self.engine = create_engine_from_config(config, echo=echo)
        init_schema(self.engine)
        self._session_factory = sessionmaker(bind=self.engine, expire_on_commit=False, future=True)
        self._encryptor: Encryptor | None = None

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

    @property
    def encryptor(self) -> Encryptor:
        if self._encryptor is None:
            self._encryptor = get_encryptor(self.config)
        return self._encryptor

    # -- signals --------------------------------------------------------

    def store_signal(
        self,
        *,
        bot_id: str,
        bot_type: str,
        signal: str,
        note: str | None = None,
        payload: dict[str, Any] | None = None,
        ts: datetime | None = None,
    ) -> int:
        with self.session() as session:
            row = Signal(
                bot_id=bot_id,
                bot_type=bot_type,
                signal=signal,
                note=note,
                payload_json=payload or {},
            )
            if ts is not None:
                row.ts = ts
            session.add(row)
            session.flush()
            return row.id

    def get_latest_signal(self, bot_id: str, bot_type: str) -> dict[str, Any] | None:
        with self.session() as session:
            row = (
                session.query(Signal)
                .filter_by(bot_id=bot_id, bot_type=bot_type)
                .order_by(Signal.ts.desc(), Signal.id.desc())
                .first()
            )
            return _row_to_dict(row) if row is not None else None

    # -- orders -----------------------------------------------------------

    def store_order(self, **fields: Any) -> int:
        with self.session() as session:
            row = Order(**fields)
            session.add(row)
            session.flush()
            return row.id

    def update_order_status(
        self,
        order_id: int,
        *,
        status: str,
        filled_at: datetime | None = None,
        raw_response: dict[str, Any] | None = None,
    ) -> None:
        with self.session() as session:
            row = session.get(Order, order_id)
            if row is None:
                raise ValueError(f"No order with id {order_id}")
            row.status = status
            if filled_at is not None:
                row.filled_at = filled_at
            if raw_response is not None:
                row.raw_response_json = raw_response

    # -- execution log ------------------------------------------------------

    def log_execution(
        self,
        *,
        level: str,
        component: str,
        message: str,
        context: dict[str, Any] | None = None,
    ) -> None:
        with self.session() as session:
            session.add(
                ExecutionLog(level=level, component=component, message=message, context_json=context)
            )

    # -- alpaca credentials (encrypted at rest) ------------------------------

    def set_alpaca_credentials(
        self, *, api_key: str, api_secret: str, base_url: str, mode: str = "paper"
    ) -> None:
        encrypted_key = self.encryptor.encrypt(api_key)
        encrypted_secret = self.encryptor.encrypt(api_secret)
        with self.session() as session:
            row = session.query(AlpacaCredentials).order_by(AlpacaCredentials.id.desc()).first()
            if row is None:
                row = AlpacaCredentials(
                    api_key_encrypted=encrypted_key,
                    api_secret_encrypted=encrypted_secret,
                    base_url=base_url,
                    mode=mode,
                    connected_at=datetime.now(timezone.utc),
                )
                session.add(row)
            else:
                row.api_key_encrypted = encrypted_key
                row.api_secret_encrypted = encrypted_secret
                row.base_url = base_url
                row.mode = mode
                row.connected_at = datetime.now(timezone.utc)

    def get_alpaca_credentials(self) -> dict[str, Any] | None:
        with self.session() as session:
            row = session.query(AlpacaCredentials).order_by(AlpacaCredentials.id.desc()).first()
            if row is None:
                return None
            return {
                "api_key": self.encryptor.decrypt(row.api_key_encrypted),
                "api_secret": self.encryptor.decrypt(row.api_secret_encrypted),
                "base_url": row.base_url,
                "mode": row.mode,
                "connected_at": row.connected_at,
            }

    # -- strategy config ------------------------------------------------------

    def upsert_strategy_config(
        self,
        *,
        bot_slug: str,
        display_name: str | None = None,
        params: dict[str, Any] | None = None,
        target_allocation: dict[str, Any] | None = None,
        is_active: bool = True,
        source: str = "local",
    ) -> None:
        with self.session() as session:
            row = session.query(StrategyConfig).filter_by(bot_slug=bot_slug).first()
            if row is None:
                row = StrategyConfig(bot_slug=bot_slug)
                session.add(row)
            row.display_name = display_name
            row.params_json = params or {}
            row.target_allocation_json = target_allocation or {}
            row.is_active = is_active
            row.source = source

    def get_active_strategy_configs(self) -> list[dict[str, Any]]:
        with self.session() as session:
            rows = session.query(StrategyConfig).filter_by(is_active=True).all()
            return [_row_to_dict(row) for row in rows]

    # -- portfolio allocation ------------------------------------------------

    def store_portfolio_allocation(
        self, *, bot_slug: str, target_weights: dict[str, Any], current_weights: dict[str, Any]
    ) -> None:
        with self.session() as session:
            session.add(
                PortfolioAllocation(
                    bot_slug=bot_slug,
                    target_weights_json=target_weights,
                    current_weights_json=current_weights,
                )
            )

    # -- market data cache ------------------------------------------------

    def cache_market_data(self, bars: list[dict[str, Any]]) -> int:
        """Insert bars that aren't already cached; returns the count inserted."""
        inserted = 0
        with self.session() as session:
            for bar in bars:
                source = bar.get("source", "unknown")
                exists = (
                    session.query(MarketDataCache.id)
                    .filter_by(symbol=bar["symbol"], ts=bar["ts"], source=source)
                    .first()
                )
                if exists is not None:
                    continue
                session.add(
                    MarketDataCache(
                        symbol=bar["symbol"],
                        ts=bar["ts"],
                        open=bar.get("open"),
                        high=bar.get("high"),
                        low=bar.get("low"),
                        close=bar.get("close"),
                        volume=bar.get("volume"),
                        source=source,
                    )
                )
                inserted += 1
        return inserted

    # -- software releases ------------------------------------------------

    def record_software_release(
        self, *, version: str, status: str = "staged", manifest: dict[str, Any] | None = None
    ) -> int:
        with self.session() as session:
            row = session.query(SoftwareRelease).filter_by(version=version).first()
            if row is None:
                row = SoftwareRelease(version=version, status=status, manifest_json=manifest or {})
                session.add(row)
            else:
                row.status = status
                if manifest is not None:
                    row.manifest_json = manifest
            session.flush()
            return row.id

    def mark_release_active(self, version: str) -> None:
        with self.session() as session:
            for row in session.query(SoftwareRelease).filter(SoftwareRelease.status == "active"):
                row.status = "rolled_back"
            target = session.query(SoftwareRelease).filter_by(version=version).first()
            if target is None:
                raise ValueError(f"No software_release row for version {version!r}")
            target.status = "active"
            target.applied_at = datetime.now(timezone.utc)
