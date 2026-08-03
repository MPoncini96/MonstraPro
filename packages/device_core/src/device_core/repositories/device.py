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
from device_core.vault import Vault


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
    pairing_code: str | None
    pairing_code_expires_at: datetime | None
    has_device_token: bool

    @property
    def is_activated(self) -> bool:
        return self.activated_at is not None

    @property
    def pairing_code_expired(self) -> bool:
        if self.pairing_code_expires_at is None:
            return True
        # SQLite (unlike Postgres) doesn't actually persist tzinfo even for a
        # DateTime(timezone=True) column - it round-trips naive, so this must
        # be assumed UTC (everything in this DB is written as UTC) before
        # comparing against an aware "now". Same fix already applied in
        # services/display/src/display/timeutil.py and
        # strategy_engine/market_data/provider.py for the identical issue.
        expires_at = self.pairing_code_expires_at
        if expires_at.tzinfo is None:
            expires_at = expires_at.replace(tzinfo=timezone.utc)
        return datetime.now(timezone.utc) >= expires_at


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
        pairing_code=row.pairing_code,
        pairing_code_expires_at=row.pairing_code_expires_at,
        has_device_token=row.device_token_encrypted is not None,
    )


class DeviceRepository:
    def __init__(self, db: Database, vault: Vault) -> None:
        self._db = db
        self._vault = vault

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
            # Burn the pairing code on activation, mirroring monstra.pro's own
            # /api/devices/pair (which nulls it out server-side once used) -
            # it's single-use and there's no reason to keep a stale plaintext
            # code around once the device is paired.
            row.pairing_code = None
            row.pairing_code_expires_at = None
            session.flush()
            return _from_row(row)

    def deactivate(self) -> Device:
        """Clears local activation state after a periodic HTTPActivationClient
        recheck confirms monstra.pro no longer considers this device paired
        (e.g. the owner disconnected it from the website - see
        NextJS_Monsta's POST /api/devices/[deviceId]/disconnect, which revokes
        this device's bearer token). Also clears the now-dead token and any
        stale pairing code so the next check_status() call re-registers from
        scratch and gets a fresh token + pairing code, exactly like a
        never-yet-activated device - mirroring that disconnect route's own
        docstring ("free to be paired again")."""
        with self._db.session() as session:
            row = session.query(DeviceRow).order_by(DeviceRow.id.asc()).first()
            if row is None:
                raise ValueError("Device has not been created yet; call get_or_create() first")
            row.activated_at = None
            row.owner_ref = None
            row.device_token_encrypted = None
            row.pairing_code = None
            row.pairing_code_expires_at = None
            session.flush()
            return _from_row(row)

    def store_registration(
        self, *, device_token: str, pairing_code: str, pairing_code_expires_at: datetime
    ) -> Device:
        """Persists the result of a monstra.pro `/api/devices/register` call:
        `device_token` is this device's own bearer credential for every
        subsequent authenticated call (`/api/devices/status`, etc.) -
        Vault-encrypted at rest, this device is the only place the raw value
        ever exists once the response is consumed. `pairing_code` is
        plaintext (see the Device model's docstring) so `display` can show
        it on the LCD for the owner to type into monstra.pro's
        /dashboard/devices/pair.

        Safe to call again before the code is used - registration is
        idempotent per serial on the monstra.pro side (a fresh call just
        reissues a new token + code), and this always overwrites whatever
        was stored before, matching that.
        """
        encrypted_token = self._vault.encrypt(device_token)
        with self._db.session() as session:
            row = session.query(DeviceRow).order_by(DeviceRow.id.asc()).first()
            if row is None:
                raise ValueError("Device has not been created yet; call get_or_create() first")
            row.device_token_encrypted = encrypted_token
            row.pairing_code = pairing_code
            row.pairing_code_expires_at = pairing_code_expires_at
            session.flush()
            return _from_row(row)

    def get_device_token(self) -> str | None:
        """Decrypts and returns this device's monstra.pro bearer token, or
        None if it has never registered. Kept separate from the `Device`
        dataclass (which only exposes `has_device_token`) so the decrypted
        secret is never returned by the general get()/get_or_create() views -
        only this explicit call touches the Vault, same boundary
        CredentialRepository.get() draws for Alpaca credentials."""
        with self._db.session() as session:
            row = session.query(DeviceRow).order_by(DeviceRow.id.asc()).first()
            if row is None or row.device_token_encrypted is None:
                return None
            return self._vault.decrypt(row.device_token_encrypted)

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
