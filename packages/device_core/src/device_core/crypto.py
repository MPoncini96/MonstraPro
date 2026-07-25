"""Secret encryption at rest.

Alpaca credentials are encrypted with a device-local Fernet key, generated
on first use and stored outside the SQLite file (a separate file with
owner-only permissions where the OS supports it), so a copy of the DB file
alone isn't enough to recover credentials. See ARCHITECTURE.md section 8.

A hardware-backed secure element is a reasonable future upgrade; not
required for V1.
"""

from __future__ import annotations

import os
import stat
from pathlib import Path

from cryptography.fernet import Fernet

from device_core.config import Config


def load_or_create_device_key(path: Path) -> bytes:
    """Return the device's Fernet key, generating and persisting one on first use."""
    if path.exists():
        return path.read_bytes()

    path.parent.mkdir(parents=True, exist_ok=True)
    key = Fernet.generate_key()
    path.write_bytes(key)
    try:
        os.chmod(path, stat.S_IRUSR | stat.S_IWUSR)  # 0600; best-effort on non-POSIX
    except OSError:
        pass
    return key


class Encryptor:
    """Encrypts/decrypts small secrets (Alpaca API key/secret) at rest."""

    def __init__(self, key: bytes) -> None:
        self._fernet = Fernet(key)

    def encrypt(self, plaintext: str) -> str:
        return self._fernet.encrypt(plaintext.encode("utf-8")).decode("ascii")

    def decrypt(self, token: str) -> str:
        return self._fernet.decrypt(token.encode("ascii")).decode("utf-8")


def get_encryptor(config: Config) -> Encryptor:
    key = load_or_create_device_key(config.device_key_path)
    return Encryptor(key)
