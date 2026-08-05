"""DeviceCore: the composition root for packages/device_core.

    core = DeviceCore.load()

    device = core.devices.get_or_create()
    core.credentials.save(mode="paper", api_key=..., api_secret=..., base_url=...)
    core.signals.store(bot_id="alpha1", bot_type="alpha1", signal="buy", payload={...})
    core.events.publish(EventType.TRADE_EXECUTED, {"bot_slug": "alpha1"})

DeviceCore.load() loads config, configures logging, opens the SQLite
database (which runs pending Alembic migrations), builds the Vault, and
wires up all eleven repositories. Nothing else in the appliance should reach
into device_core.db or device_core.repositories directly - DeviceCore is
the boundary trading_worker/display/updater are expected to depend on.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from device_core.config import Config, load_config
from device_core.db.session import Database
from device_core.logging import configure_logging
from device_core.repositories import (
    AccountSnapshotRepository,
    BotStateRepository,
    BotValueSnapshotRepository,
    CredentialRepository,
    DeviceEventRepository,
    DeviceRepository,
    ExecutionLogRepository,
    ManualHoldingRepository,
    MarketDataCacheRepository,
    OrderRepository,
    PortfolioAllocationRepository,
    PositionSnapshotRepository,
    SignalRepository,
    SoftwareReleaseRepository,
    StrategyConfigRepository,
)
from device_core.vault import Vault


@dataclass(frozen=True)
class DeviceCore:
    config: Config
    database: Database
    devices: DeviceRepository
    credentials: CredentialRepository
    strategies: StrategyConfigRepository
    allocations: PortfolioAllocationRepository
    signals: SignalRepository
    events: DeviceEventRepository
    logs: ExecutionLogRepository
    orders: OrderRepository
    bot_states: BotStateRepository
    account_snapshots: AccountSnapshotRepository
    positions: PositionSnapshotRepository
    bot_values: BotValueSnapshotRepository
    manual_holdings: ManualHoldingRepository
    software_releases: SoftwareReleaseRepository
    market_data: MarketDataCacheRepository
    vault: Vault

    @classmethod
    def load(cls, overrides: Mapping[str, Any] | None = None) -> "DeviceCore":
        config = load_config(overrides)
        configure_logging(config)
        database = Database(config)
        vault = Vault.load_or_create(config.encryption_key_path)

        return cls(
            config=config,
            database=database,
            devices=DeviceRepository(database, vault),
            credentials=CredentialRepository(database, vault),
            strategies=StrategyConfigRepository(database),
            allocations=PortfolioAllocationRepository(database),
            signals=SignalRepository(database),
            events=DeviceEventRepository(database),
            logs=ExecutionLogRepository(database),
            orders=OrderRepository(database),
            bot_states=BotStateRepository(database),
            account_snapshots=AccountSnapshotRepository(database),
            positions=PositionSnapshotRepository(database),
            bot_values=BotValueSnapshotRepository(database),
            manual_holdings=ManualHoldingRepository(database),
            software_releases=SoftwareReleaseRepository(database),
            market_data=MarketDataCacheRepository(database),
            vault=vault,
        )

    def close(self) -> None:
        self.database.close()
