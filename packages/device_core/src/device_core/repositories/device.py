"""DeviceRepository: the single-row `device` table.

    device = core.devices.get_or_create()
    if not device.is_activated:
        ...
    device = core.devices.activate(owner_ref="cust_123")
"""

from __future__ import annotations

import secrets
from dataclasses import dataclass
from datetime import datetime, timezone

from device_core.db.models import Device as DeviceRow
from device_core.db.session import Database


def _generate_serial() -> str:
    return f"MPB-{secrets.token_hex(6).upper()}"


def _generate_local_pin() -> str:
    """A 6-digit numeric PIN - short enough to read off a small LCD and
    type on a phone keyboard. See device_core.db.models.Device's docstring
    for why this is plaintext, not hashed like Alpaca credentials."""
    return f"{secrets.randbelow(1_000_000):06d}"


@dataclass(frozen=True)
class Device:
    id: int
    serial: str
    activation_code_hash: str | None
    activated_at: datetime | None
    owner_ref: str | None
    disclosures_accepted_at: datetime | None
    software_version: str | None
    local_pin: str | None

    @property
    def is_activated(self) -> bool:
        return self.activated_at is not None


def _from_row(row: DeviceRow) -> Device:
    return Device(
        id=row.id,
        serial=row.serial,
        activation_code_hash=row.activation_code_hash,
        activated_at=row.activated_at,
        owner_ref=row.owner_ref,
        disclosures_accepted_at=row.disclosures_accepted_at,
        software_version=row.software_version,
        local_pin=row.local_pin,
    )


class DeviceRepository:
    def __init__(self, db: Database) -> None:
        self._db = db

    def get_or_create(self) -> Device:
        """Idempotent: returns the existing device row, creating one with a
        fresh serial only if none exists yet."""
        with self._db.session() as session:
            row = session.query(DeviceRow).order_by(DeviceRow.id.asc()).first()
            if row is None:
                row = DeviceRow(serial=_generate_serial())
                session.add(row)
                session.flush()
            return _from_row(row)

    def get(self) -> Device | None:
        with self._db.session() as session:
            row = session.query(DeviceRow).order_by(DeviceRow.id.asc()).first()
            return _from_row(row) if row is not None else None

    def activate(self, *, owner_ref: str, disclosures_accepted: bool = True) -> Device:
        with self._db.session() as session:
            row = session.query(DeviceRow).order_by(DeviceRow.id.asc()).first()
            if row is None:
                raise ValueError("Device has not been created yet; call get_or_create() first")
            row.owner_ref = owner_ref
            row.activated_at = datetime.now(timezone.utc)
            if disclosures_accepted:
                row.disclosures_accepted_at = datetime.now(timezone.utc)
            session.flush()
            return _from_row(row)

    def get_or_create_local_pin(self) -> str:
        """Idempotent, same lazy-generation pattern as get_or_create()'s
        serial: returns the existing PIN if one's already stored, else
        generates and persists one. Never regenerates an existing PIN (a
        stable PIN is the point - the owner writes it down/remembers it)."""
        with self._db.session() as session:
            row = session.query(DeviceRow).order_by(DeviceRow.id.asc()).first()
            if row is None:
                row = DeviceRow(serial=_generate_serial())
                session.add(row)
                session.flush()
            if row.local_pin is None:
                row.local_pin = _generate_local_pin()
                session.flush()
            return row.local_pin

    def record_software_version(self, version: str) -> Device:
        with self._db.session() as session:
            row = session.query(DeviceRow).order_by(DeviceRow.id.asc()).first()
            if row is None:
                raise ValueError("Device has not been created yet; call get_or_create() first")
            row.software_version = version
            session.flush()
            return _from_row(row)
