import base64

import pytest
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from cryptography.hazmat.primitives.serialization import Encoding, PublicFormat

from updater.signature import SignatureVerificationError, load_public_key, verify


@pytest.fixture
def keypair():
    private_key = Ed25519PrivateKey.generate()
    return private_key, private_key.public_key()


def _public_key_bytes(public_key) -> bytes:
    return public_key.public_bytes(Encoding.Raw, PublicFormat.Raw)


def test_verify_accepts_valid_signature(keypair):
    private_key, public_key = keypair
    artifact = b"release-artifact-bytes"
    signature_b64 = base64.b64encode(private_key.sign(artifact)).decode()

    assert verify(artifact, signature_b64, public_key) is True


def test_verify_rejects_tampered_artifact(keypair):
    private_key, public_key = keypair
    signature_b64 = base64.b64encode(private_key.sign(b"original")).decode()

    assert verify(b"tampered", signature_b64, public_key) is False


def test_verify_rejects_signature_from_a_different_key(keypair):
    _, public_key = keypair
    other_private_key = Ed25519PrivateKey.generate()
    artifact = b"release-artifact-bytes"
    signature_b64 = base64.b64encode(other_private_key.sign(artifact)).decode()

    assert verify(artifact, signature_b64, public_key) is False


def test_verify_raises_on_malformed_base64(keypair):
    _, public_key = keypair

    with pytest.raises(SignatureVerificationError):
        verify(b"artifact", "not-valid-base64!!!", public_key)


def test_load_public_key_round_trips(tmp_path, keypair):
    _, public_key = keypair
    key_path = tmp_path / "release_signing_key.pub"
    key_path.write_bytes(_public_key_bytes(public_key))

    loaded = load_public_key(key_path)

    assert _public_key_bytes(loaded) == _public_key_bytes(public_key)


def test_load_public_key_missing_file_raises(tmp_path):
    with pytest.raises(SignatureVerificationError):
        load_public_key(tmp_path / "nonexistent.pub")


def test_load_public_key_invalid_bytes_raises(tmp_path):
    key_path = tmp_path / "bad.pub"
    key_path.write_bytes(b"not a real key")

    with pytest.raises(SignatureVerificationError):
        load_public_key(key_path)
