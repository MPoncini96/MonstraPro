"""Release artifact signature verification (ARCHITECTURE.md section 8:
"Release artifacts are signature-verified before being applied; the
updater refuses to extract/activate an unsigned or badly-signed release.").

Ed25519 (via `cryptography`, already a device_core dependency for Vault) -
small keys/signatures, fast verification, no parameter choices to get
wrong, appropriate for a single verify-only use on a resource-constrained
Pi. Real verification logic, tested against a self-generated keypair below
and in tests/test_signature.py.

What's explicitly NOT solved here: how the public key actually gets "baked
into the base image" (ARCHITECTURE.md's phrase) - that's an image-build /
provisioning concern, not code. `load_public_key()` just reads 32 raw
public-key bytes from a file path; nothing here creates or provisions that
file. Until a real base-image build process exists, there is no real public
key on any device, which is exactly why `manifest_client.py`'s
NullManifestClient never produces a manifest to verify in the first place.
"""

from __future__ import annotations

import base64
from pathlib import Path

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey


class SignatureVerificationError(Exception):
    """Raised for a badly-formed key/signature, as distinct from a
    well-formed signature that simply doesn't verify (see verify())."""


def load_public_key(path: Path) -> Ed25519PublicKey:
    try:
        raw = path.read_bytes()
    except OSError as exc:
        raise SignatureVerificationError(f"could not read public key at {path}: {exc}") from exc
    try:
        return Ed25519PublicKey.from_public_bytes(raw)
    except ValueError as exc:
        raise SignatureVerificationError(f"invalid Ed25519 public key at {path}: {exc}") from exc


def verify(artifact_bytes: bytes, signature_b64: str, public_key: Ed25519PublicKey) -> bool:
    """True if `signature_b64` (base64-encoded) is a valid Ed25519
    signature of `artifact_bytes` under `public_key`. False for a
    well-formed-but-non-matching signature; raises SignatureVerificationError
    for a malformed signature string."""
    try:
        signature = base64.b64decode(signature_b64, validate=True)
    except (ValueError, TypeError) as exc:
        raise SignatureVerificationError(f"signature is not valid base64: {exc}") from exc

    try:
        public_key.verify(signature, artifact_bytes)
        return True
    except InvalidSignature:
        return False
