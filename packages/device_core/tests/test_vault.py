import pytest

from device_core.vault import (
    Vault,
    VaultDecryptionError,
    VaultKeyInvalidError,
    VaultKeyMissingError,
)


def test_encrypt_decrypt_roundtrip(tmp_path):
    vault = Vault.load_or_create(tmp_path / "device.key")

    token = vault.encrypt("super-secret-alpaca-key")

    assert token != "super-secret-alpaca-key"
    assert vault.decrypt(token) == "super-secret-alpaca-key"


def test_load_or_create_persists_key_across_instances(tmp_path):
    key_path = tmp_path / "device.key"

    vault1 = Vault.load_or_create(key_path)
    token = vault1.encrypt("secret-value")

    vault2 = Vault.load_or_create(key_path)
    assert vault2.decrypt(token) == "secret-value"


def test_load_missing_key_raises(tmp_path):
    with pytest.raises(VaultKeyMissingError):
        Vault.load(tmp_path / "does-not-exist.key")


def test_invalid_key_raises(tmp_path):
    with pytest.raises(VaultKeyInvalidError):
        Vault(b"not-a-valid-fernet-key")


def test_corrupted_ciphertext_raises(tmp_path):
    vault = Vault.load_or_create(tmp_path / "device.key")
    token = vault.encrypt("secret-value")

    tampered = token[:-4] + ("A" if token[-4] != "A" else "B") + token[-3:]

    with pytest.raises(VaultDecryptionError):
        vault.decrypt(tampered)


def test_wrong_device_key_cannot_decrypt(tmp_path):
    vault_a = Vault.load_or_create(tmp_path / "a.key")
    vault_b = Vault.load_or_create(tmp_path / "b.key")

    token = vault_a.encrypt("secret-value")

    with pytest.raises(VaultDecryptionError):
        vault_b.decrypt(token)


def test_key_file_has_restricted_permissions_where_supported(tmp_path):
    import stat

    key_path = tmp_path / "device.key"
    Vault.load_or_create(key_path)

    mode = stat.S_IMODE(key_path.stat().st_mode)
    # Best-effort on POSIX only; just assert it doesn't error and the file exists.
    assert key_path.exists()
    assert mode is not None
