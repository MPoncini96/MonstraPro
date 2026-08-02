"""updater entrypoint — systemd target monstrapro-updater.service,
triggered by monstrapro-updater.timer (see deploy/systemd/).

Responsibilities (see ARCHITECTURE.md section 4.3):

  1. Fetch the current release manifest from monstra.pro (device-token
     authenticated) - manifest_client.py. Also carries algorithm universe
     updates and notifications (Objectives.txt) - strategy_sync.py.
  2. Compare against software_release; if newer, download the signed
     artifact and verify its signature (signature.py) before touching
     anything.
  3. Extract to releases/<version>/, never overwriting the running release
     in place (release_store.py).
  4. Atomically repoint the `current` symlink and `systemctl restart`
     monstrapro-worker + monstrapro-display. No separate "run pending DB
     migration" step is needed here - device_core.db.session.Database runs
     migrations to head on open, so the restarted services pick up schema
     changes themselves on their next startup.
  5. Wait for a health grace period; roll the symlink back and restart
     again if either service isn't still active. Keep the last 3 releases
     on disk for rollback.

One-shot process (not a long-running daemon) — the timer unit is what makes
it periodic. `run_once()` is the testable orchestration (every I/O edge —
HTTP download, systemctl, sleep — is an injectable parameter); `main()` is
the thin real-dependency wiring, deliberately not unit tested, same as
trading_worker/display's entrypoints.
"""

from __future__ import annotations

import logging
import subprocess
import time
from pathlib import Path
from typing import Callable

import requests
from device_core.core import DeviceCore
from device_core.events import EventType

from updater import release_store
from updater.manifest_client import NullManifestClient, ReleaseManifestClient
from updater.signature import SignatureVerificationError, load_public_key, verify as verify_signature
from updater.strategy_sync import publish_notifications, sync_strategy_updates

logger = logging.getLogger(__name__)

HEALTH_CHECK_GRACE_SECONDS = 30
KEEP_RELEASES = 3
SERVICES_TO_RESTART = ("monstrapro-worker.service", "monstrapro-display.service")
PUBLIC_KEY_FILENAME = "release_signing_key.pub"


def _http_download(url: str) -> bytes:
    response = requests.get(url, timeout=120)
    response.raise_for_status()
    return response.content


def _systemctl_restart(service: str) -> None:
    subprocess.run(["systemctl", "restart", service], check=True, timeout=30)


def _systemctl_is_active(service: str) -> bool:
    result = subprocess.run(["systemctl", "is-active", service], capture_output=True, text=True, timeout=10)
    return result.returncode == 0 and result.stdout.strip() == "active"


def run_once(
    core: DeviceCore,
    manifest_client: ReleaseManifestClient,
    *,
    release_dir_root: Path,
    download_artifact: Callable[[str], bytes] = _http_download,
    restart_service: Callable[[str], None] = _systemctl_restart,
    is_service_active: Callable[[str], bool] = _systemctl_is_active,
    sleep: Callable[[float], None] = time.sleep,
    health_check_grace_seconds: int = HEALTH_CHECK_GRACE_SECONDS,
) -> dict:
    manifest = manifest_client.fetch()
    if manifest is None:
        return {"status": "no_manifest"}

    updated_bots = sync_strategy_updates(core, manifest)
    notified = publish_notifications(core, manifest)
    result: dict = {"status": "no_update", "strategy_updates": updated_bots, "notifications": notified}

    installed = core.software_releases.get_active()
    installed_version = installed["version"] if installed else None

    if manifest.artifact_url is None or not release_store.is_newer(manifest.version, installed_version):
        return result

    if not manifest.artifact_signature:
        core.logs.record(
            level="ERROR", component="updater",
            message=f"release {manifest.version} has no signature; refusing to apply",
        )
        result["status"] = "unsigned_release_rejected"
        return result

    core.events.publish(EventType.UPDATE_AVAILABLE, {"version": manifest.version})

    try:
        public_key = load_public_key(release_dir_root / PUBLIC_KEY_FILENAME)
    except SignatureVerificationError as exc:
        core.logs.record(level="ERROR", component="updater", message=str(exc))
        result["status"] = "no_public_key"
        return result

    artifact_bytes = download_artifact(manifest.artifact_url)
    if not verify_signature(artifact_bytes, manifest.artifact_signature, public_key):
        core.logs.record(
            level="ERROR", component="updater",
            message=f"signature verification failed for release {manifest.version}",
        )
        result["status"] = "signature_invalid"
        return result

    archive_path = release_dir_root / f".{manifest.version}.tar.gz"
    archive_path.write_bytes(artifact_bytes)
    try:
        release_store.extract_release(archive_path, release_dir_root / "releases", manifest.version)
    finally:
        archive_path.unlink(missing_ok=True)

    previous_version = release_store.current_version(release_dir_root)
    core.software_releases.stage(manifest.version, manifest={"artifact_url": manifest.artifact_url})
    release_store.swap_current_symlink(release_dir_root, manifest.version)
    core.software_releases.activate(manifest.version)

    for service in SERVICES_TO_RESTART:
        restart_service(service)
    sleep(health_check_grace_seconds)

    if all(is_service_active(service) for service in SERVICES_TO_RESTART):
        core.events.publish(EventType.UPDATE_APPLIED, {"version": manifest.version})
        release_store.prune_old_releases(release_dir_root / "releases", keep=KEEP_RELEASES)
        result["status"] = "applied"
        result["version"] = manifest.version
        return result

    logger.error("release %s failed health check; rolling back", manifest.version)
    core.logs.record(
        level="ERROR", component="updater",
        message=f"release {manifest.version} failed health check; rolling back",
    )
    if previous_version is not None:
        release_store.swap_current_symlink(release_dir_root, previous_version)
        core.software_releases.rollback_to(previous_version)
        for service in SERVICES_TO_RESTART:
            restart_service(service)
    result["status"] = "rolled_back"
    return result


def main() -> None:
    core = DeviceCore.load()
    manifest_client = NullManifestClient()
    result = run_once(core, manifest_client, release_dir_root=core.config.release_dir)
    logger.info("updater run complete: %s", result)


if __name__ == "__main__":
    main()
