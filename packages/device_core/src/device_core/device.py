"""Device identity and activation state - the single-row `device` table.

Usage:

    db = Database(config)
    device = Device.load(db)
    if not device.is_activated:
        ...  # poll monstra.pro, publish awaiting_activation events
    device = device.activate(db, owner_ref="cust_123")
"""

from __future__ import annotations

import secrets
from dataclasses import dataclass
from datetime import datetime, timezone

from device_core.db.database import Database
from device_core.db.models import Device as DeviceRow


def _generate_serial() -> str:
    return f"MPB-{secrets.token_hex(6).upper()}"


@dataclass(frozen=True)
class Device:
    id: int
    serial: str
    activation_code_hash: str | None
    activated_at: datetime | None
    owner_ref: str | None
    disclosures_accepted_at: datetime | None
    software_version: str | None

    @property
    def is_activated(self) -> bool:
        return self.activated_at is not None

    @classmethod
    def load(cls, db: Database) -> Device:
        """Return this device's row, creating one with a fresh serial on first run."""
        with db.session() as session:
            row = session.query(DeviceRow).order_by(DeviceRow.id.asc()).first()
            if row is None:
                row = DeviceRow(serial=_generate_serial())
                session.add(row)
                session.flush()
            return cls._from_row(row)

    @classmethod
    def _from_row(cls, row: DeviceRow) -> Device:
        return cls(
            id=row.id,
            serial=row.serial,
            activation_code_hash=row.activation_code_hash,
            activated_at=row.activated_at,
            owner_ref=row.owner_ref,
            disclosures_accepted_at=row.disclosures_accepted_at,
            software_version=row.software_version,
        )

    def activate(self, db: Database, *, owner_ref: str, disclosures_accepted: bool = True) -> Device:
        with db.session() as session:
            row = session.get(DeviceRow, self.id)
            if row is None:
                raise ValueError(f"No device row with id {self.id}")
            row.owner_ref = owner_ref
            row.activated_at = datetime.now(timezone.utc)
            if disclosures_accepted:
                row.disclosures_accepted_at = datetime.now(timezone.utc)
            session.flush()
            return self._from_row(row)

    def record_software_version(self, db: Database, version: str) -> Device:
        with db.session() as session:
            row = session.get(DeviceRow, self.id)
            if row is None:
                raise ValueError(f"No device row with id {self.id}")
            row.software_version = version
            session.flush()
            return self._from_row(row)
