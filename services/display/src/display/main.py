"""display entrypoint — systemd target monstrapro-display.service.

Responsibilities (see ARCHITECTURE.md section 4.2), not yet implemented:

  1. Init a native renderer against the framebuffer/DRM (no browser, no
     window manager — keeps boot time and footprint low on a 2GB Pi 5).
  2. Subscribe to device_core.events (device_event table, polled) and drive
     a state machine: idle / awaiting_activation / trade_wake / idle again.
  3. Overlay a persistent connection-status banner (Wi-Fi, Alpaca, update
     available) regardless of which state is active.

Has no direct dependency on trading_worker internals — everything comes
through device_core.events, so display can crash or be swapped for a
different rendering backend without touching trading logic.
"""

from __future__ import annotations


def main() -> None:
    raise NotImplementedError("display is not yet implemented — see module docstring")


if __name__ == "__main__":
    main()
