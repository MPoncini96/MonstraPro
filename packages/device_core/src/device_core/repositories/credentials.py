"""CredentialRepository: encrypted Alpaca credentials, one row per mode.

Paper and live credentials coexist as independent rows (unique on `mode`),
so activating live trading doesn't require discarding a paper connection.
Plaintext never reaches SQLite - only Vault-encrypted ciphertext.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from device_core.db.models import AlpacaCredentials
from device_core.db.session import Database
from device_core.vault import Vault

_VALID_MODES = frozenset({"paper", "live"})


class CredentialRepository:
    def __init__(self, db: Database, vault: Vault) -> None:
        self._db = db
        self._vault = vault

    def save(self, *, mode: str, api_key: str, api_secret: str, base_url: str) -> None:
        if mode not in _VALID_MODES:
            raise ValueError(f"mode must be one of {sorted(_VALID_MODES)}, got {mode!r}")

        encrypted_key = self._vault.encrypt(api_key)
        encrypted_secret = self._vault.encrypt(api_secret)
        with self._db.session() as session:
            row = session.query(AlpacaCredentials).filter_by(mode=mode).first()
            if row is None:
                row = AlpacaCredentials(mode=mode)
                session.add(row)
            row.api_key_encrypted = encrypted_key
            row.api_secret_encrypted = encrypted_secret
            row.base_url = base_url
            row.connected_at = datetime.now(timezone.utc)

    def get(self, mode: str) -> dict[str, Any] | None:
        with self._db.session() as session:
            row = session.query(AlpacaCredentials).filter_by(mode=mode).first()
            if row is None:
                return None
            return {
                "mode": row.mode,
                "api_key": self._vault.decrypt(row.api_key_encrypted),
                "api_secret": self._vault.decrypt(row.api_secret_encrypted),
                "base_url": row.base_url,
                "connected_at": row.connected_at,
            }

    def delete(self, mode: str) -> None:
        with self._db.session() as session:
            row = session.query(AlpacaCredentials).filter_by(mode=mode).first()
            if row is not None:
                session.delete(row)
