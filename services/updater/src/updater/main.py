"""updater entrypoint — systemd target monstrapro-updater.service,
triggered by monstrapro-updater.timer (see deploy/systemd/).

Responsibilities (see ARCHITECTURE.md section 4.3), not yet implemented:

  1. Fetch the current release manifest from monstra.pro (device-token
     authenticated).
  2. Compare against software_release; if newer, download the signed
     artifact and verify its signature before touching anything.
  3. Extract to releases/<version>/, never overwriting the running release
     in place.
  4. Atomically repoint the `current` symlink, run pending DB migrations,
     and `systemctl restart` monstrapro-worker + monstrapro-display.
  5. Wait for a health grace period; roll the symlink back and restart
     again if trading_worker doesn't report healthy in time. Keep the last
     3 releases on disk for rollback.

One-shot process (not a long-running daemon) — the timer unit is what makes
it periodic.
"""

from __future__ import annotations


def main() -> None:
    raise NotImplementedError("updater is not yet implemented — see module docstring")


if __name__ == "__main__":
    main()
