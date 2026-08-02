"""display entrypoint — systemd target monstrapro-display.service.

Responsibilities (see ARCHITECTURE.md section 4.2):

  1. Init a native renderer (pygame_renderer.PygameRenderer, windowed on a
     dev machine / KMSDRM on the real device via SDL_VIDEODRIVER).
  2. Poll device_core.events and drive state.StateMachine: idle /
     wifi_setup / awaiting_activation / trade_wake, plus a connection-status
     banner.
  3. While idle, rotate through three sub-views on a fixed cadence
     (idle_rotation.py: 15s portfolio candlestick + last trade, 15s a
     rotating active bot's performance, 10s a rotating top-mover stock's
     price) - see _render_idle below.

Has no direct dependency on trading_worker internals — everything comes
through device_core.events/repositories, so display can crash or be
swapped for a different rendering backend without touching trading logic.
"""

from __future__ import annotations

import logging
import time
from datetime import datetime, timezone

from device_core.core import DeviceCore

from display.bot_view import build_bot_view
from display.idle_rotation import IdlePhase, phase_at
from display.last_trade import build_last_trade
from display.pygame_renderer import PygameRenderer
from display.renderer import Renderer
from display.snapshot import build_snapshot
from display.state import ScreenState, StateMachine
from display.stock_view import build_stock_view, top_movers

logger = logging.getLogger(__name__)

CONSUMER_NAME = "display"

# The shortest idle-rotation phase is 10 seconds (idle_rotation.STOCK_SECONDS)
# - polling any slower than that would risk skipping straight past a phase
# without ever rendering it. Also bounds device_event polling latency to the
# same tick, which is a reasonable default regardless (event_poll_interval_seconds
# stays configurable/respected when set even lower than this).
IDLE_ROTATION_TICK_SECONDS = 2


def _render_idle(core: DeviceCore, renderer: Renderer, *, now: datetime, banner: str | None) -> None:
    rotation = phase_at(now)
    # get_or_create_local_pin() is idempotent - cheap after the first call,
    # and guarantees the footer (services/portfolio_web's local page) is
    # never blank even on a very first render before anything else has
    # touched the device row.
    local_pin = core.devices.get_or_create_local_pin()

    if rotation.phase == IdlePhase.BOT:
        bot_slugs = [row["bot_slug"] for row in core.strategies.get_active()]
        if bot_slugs:
            bot_slug = bot_slugs[rotation.cycle_index % len(bot_slugs)]
            renderer.render_idle_bot(build_bot_view(core, bot_slug), banner, local_pin=local_pin)
            return
        # No active bots configured yet - fall through to the portfolio
        # view rather than rendering an empty/broken bot screen.

    if rotation.phase == IdlePhase.STOCK:
        symbols = top_movers(core)
        if symbols:
            symbol = symbols[rotation.cycle_index % len(symbols)]
            renderer.render_idle_stock(build_stock_view(core, symbol), banner, local_pin=local_pin)
            return
        # No currently-held positions to rank yet - fall through to the
        # portfolio view for the same reason as above.

    snapshot = build_snapshot(core, now=now)
    last_trade = build_last_trade(core)
    renderer.render_idle(snapshot, last_trade, banner, local_pin=local_pin)


def main() -> None:
    core = DeviceCore.load()
    renderer = PygameRenderer()
    renderer.init()
    machine = StateMachine()
    poll_interval = min(core.config.event_poll_interval_seconds, IDLE_ROTATION_TICK_SECONDS)

    try:
        while True:
            if not renderer.pump_events():
                break

            now = datetime.now(timezone.utc)
            events = core.events.list_unconsumed(limit=100)
            machine = machine.advance(events, now=now)
            for event in events:
                core.events.mark_consumed(event["id"], consumer=CONSUMER_NAME)

            if machine.screen == ScreenState.WIFI_SETUP:
                renderer.render_wifi_setup(machine.ap_ssid, machine.setup_url, machine.top_banner)
            elif machine.screen == ScreenState.AWAITING_ACTIVATION:
                renderer.render_awaiting_activation(machine.device_serial, machine.top_banner)
            elif machine.screen == ScreenState.TRADE_WAKE:
                snapshot = build_snapshot(core, now=now)
                renderer.render_trade_wake(snapshot, machine.top_banner)
            else:
                _render_idle(core, renderer, now=now, banner=machine.top_banner)

            time.sleep(poll_interval)
    finally:
        renderer.shutdown()


if __name__ == "__main__":
    main()
