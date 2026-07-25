"""Device-local authenticated encryption for secrets at rest.

Alpaca credentials are encrypted with Fernet (AES-128-CBC + HMAC - an
authenticated construction, so tampering is detected, not just malformed
data) under a key generated on first use and stored *outside* the SQLite
file, so a copy of the .db alone can't recover credentials.

Key creation is atomic: written to a temp file created with O_CREAT|O_EXCL
and owner-only mode from the moment it's created, then renamed into place -
there's no window where a partial or world-readable key file exists.
"""

from __future__ import annotations

import os
import stat
from pathlib import Path

from cryptography.fernet import Fernet, InvalidToken


class VaultError(Exception):
    """Base class for vault errors."""


class VaultKeyMissingError(VaultError):
    """Raised when Vault.load() is asked for a key that doesn't exist yet."""


class VaultKeyInvalidError(VaultError):
    """Raised when the on-disk key is malformed and can't be used."""


class VaultDecryptionError(VaultError):
    """Raised when ciphertext can't be decrypted - wrong key or corruption.

    Deliberately doesn't distinguish the two: either way the caller can't
    recover the plaintext, and the message shouldn't imply which it was
    since that itself is information about the ciphertext/key.
    """


def _create_key_atomically(path: Path) -> bytes:
    path.parent.mkdir(parents=True, exist_ok=True)
    key = Fernet.generate_key()
    tmp_path = path.with_name(f"{path.name}.tmp-{os.getpid()}")
    try:
        fd = os.open(str(tmp_path), os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(fd, "wb") as fh:
            fh.write(key)
        os.replace(tmp_path, path)
    except BaseException:
        tmp_path.unlink(missing_ok=True)
        raise
    try:
        os.chmod(path, stat.S_IRUSR | stat.S_IWUSR)  # best-effort on non-POSIX (Windows dev)
    except OSError:
        pass
    return key


class Vault:
    """Encrypts/decrypts small secrets (Alpaca API key/secret) at rest."""

    def __init__(self, key: bytes) -> None:
        try:
            self._fernet = Fernet(key)
        except Exception as exc:
            raise VaultKeyInvalidError("Device encryption key is malformed") from exc

    def encrypt(self, plaintext: str) -> str:
        return self._fernet.encrypt(plaintext.encode("utf-8")).decode("ascii")

    def decrypt(self, token: str) -> str:
        try:
            return self._fernet.decrypt(token.encode("ascii")).decode("utf-8")
        except (InvalidToken, ValueError) as exc:
            raise VaultDecryptionError(
                "Could not decrypt ciphertext - it is corrupted or was not produced "
                "by this device's current encryption key"
            ) from exc

    @classmethod
    def load_or_create(cls, key_path: Path) -> Vault:
        if key_path.exists():
            return cls(key_path.read_bytes())
        return cls(_create_key_atomically(key_path))

    @classmethod
    def load(cls, key_path: Path) -> Vault:
        if not key_path.exists():
            raise VaultKeyMissingError(f"No device encryption key at {key_path}")
        return cls(key_path.read_bytes())
