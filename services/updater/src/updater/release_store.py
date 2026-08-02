"""On-disk release management: extract, atomically swap the `current`
symlink, prune old releases. Application-level (versioned directories + a
symlink), not a full OS image A/B scheme — ARCHITECTURE.md section 4.3:
"appropriate for V1's 'prove the concept' scope."

Layout under `config.release_dir`:
    releases/
        1.0.0/
        1.1.0/
    current -> releases/1.1.0   (symlink, lives alongside `releases/`)
"""

from __future__ import annotations

import shutil
import tarfile
from pathlib import Path


class ReleaseStoreError(Exception):
    pass


def parse_version(version: str) -> tuple[int, ...]:
    """"1.2.3" -> (1, 2, 3). Non-numeric components raise - versions are
    expected to be plain dotted-integer strings, not full semver (no
    pre-release/build-metadata suffixes) for this simple V1 scheme."""
    try:
        return tuple(int(part) for part in version.split("."))
    except ValueError as exc:
        raise ReleaseStoreError(f"version {version!r} is not a dotted-integer string") from exc


def is_newer(candidate: str, current: str | None) -> bool:
    if current is None:
        return True
    return parse_version(candidate) > parse_version(current)


def extract_release(archive_path: Path, releases_dir: Path, version: str) -> Path:
    """Extract `archive_path` (a tar.gz) into releases_dir/version/. Refuses
    to overwrite an existing directory for that version - a release is
    extracted once, never mutated in place."""
    target = releases_dir / version
    if target.exists():
        raise ReleaseStoreError(f"release {version!r} already extracted at {target}")

    releases_dir.mkdir(parents=True, exist_ok=True)
    staging = releases_dir / f".{version}.staging"
    if staging.exists():
        shutil.rmtree(staging)

    try:
        with tarfile.open(archive_path) as tar:
            tar.extractall(staging, filter="data")  # "data" filter rejects path traversal/device files
    except Exception:
        if staging.exists():
            shutil.rmtree(staging, ignore_errors=True)
        raise

    staging.rename(target)
    return target


def swap_current_symlink(release_dir_root: Path, version: str) -> Path:
    """Atomically repoint `release_dir_root/current` at
    `release_dir_root/releases/version`. Atomic via symlink-then-rename:
    a half-written symlink is never visible at the `current` path."""
    target = release_dir_root / "releases" / version
    if not target.is_dir():
        raise ReleaseStoreError(f"release {version!r} has not been extracted at {target}")

    current_path = release_dir_root / "current"
    temp_link = release_dir_root / f".current.{version}.tmp"
    if temp_link.exists() or temp_link.is_symlink():
        temp_link.unlink()

    temp_link.symlink_to(target, target_is_directory=True)
    temp_link.replace(current_path)
    return current_path


def current_version(release_dir_root: Path) -> str | None:
    current_path = release_dir_root / "current"
    if not current_path.is_symlink():
        return None
    return current_path.resolve().name


def prune_old_releases(releases_dir: Path, *, keep: int = 3) -> list[str]:
    """Delete all but the `keep` highest-versioned release directories.
    Returns the versions that were deleted."""
    if not releases_dir.is_dir():
        return []

    versions = sorted(
        (entry.name for entry in releases_dir.iterdir() if entry.is_dir() and not entry.name.startswith(".")),
        key=parse_version,
        reverse=True,
    )
    to_delete = versions[keep:]
    for version in to_delete:
        shutil.rmtree(releases_dir / version, ignore_errors=True)
    return to_delete
