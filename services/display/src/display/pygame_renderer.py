"""pygame-ce implementation of the Renderer protocol.

Video driver selection is left to SDL's own `SDL_VIDEODRIVER` environment
variable rather than hardcoded here: unset (or "windib"/"x11"/"cocoa") gives
a normal desktop window, which is how this was actually run and visually
checked during development on Windows.

The real device is a different story, confirmed on actual Pi 5 hardware:
this panel (goodtft/MHS35) has no /dev/dri at all, so `SDL_VIDEODRIVER=kmsdrm`
- the original plan, referenced by the now-deleted deploy/systemd's
EnvironmentFile - can never work here. Every real SDL video driver probed as
"not available" (no DRM device, no X/Wayland compositor); only the invisible
`dummy`/`offscreen` ones succeed. `/etc/monstrapro/env` (image/scripts/install.sh)
instead sets `SDL_VIDEODRIVER=dummy` plus `MONSTRAPRO_FB_DEVICE=/dev/fb0` -
pygame renders normally off-screen, and this class hands the finished frame
to display.framebuffer.FramebufferWriter, which mmaps /dev/fb0 and writes
the real pixels there directly. See framebuffer.py's module docstring.

Screen resolution is a constructor argument, not a hardware constant. When
MONSTRAPRO_FB_DEVICE is set and no explicit size was passed in, it's
auto-detected from the framebuffer's own /sys/class/graphics/fb0/virtual_size
rather than assumed - confirmed on real hardware to be 480x320, not the
800x480 dev-window default below (see "What remains" in image/README.md for
the layout-tightness consequence of that gap, not addressed here).

render_idle's layout (header, bots list, candle chart) is comfortable at
the 800x480 default but genuinely tight at the real panel's confirmed
480x320 (via /sys/class/graphics/fb0/virtual_size on real Pi 5 hardware)
once 3 bots are active, since fixed pixel offsets don't adapt to available
height. Verified by headless render during development (SDL_VIDEODRIVER=dummy
+ pygame.image.save), same technique that caught the original
timezone/banner-overlap bugs. Not solved with a responsive layout in this
pass - still flagged in image/README.md "What remains".
"""

from __future__ import annotations

import os
from datetime import datetime, timedelta, timezone

import pygame

from display.bot_view import BotView
from display.candles import Candle
from display.framebuffer import FramebufferWriter
from display.last_trade import LastTradeInfo
from display.snapshot import DisplaySnapshot, as_utc
from display.stock_view import StockView

DEFAULT_SIZE = (800, 480)
_BANNER_HEIGHT = 36
_CHART_HEIGHT = 70
_FOOTER_RESERVE = 28

_BG = (12, 14, 20)
_FG = (230, 232, 238)
_MUTED = (140, 145, 156)
_GREEN = (60, 200, 120)
_RED = (220, 80, 90)
_YELLOW = (230, 190, 60)
_BANNER_BG = (120, 40, 40)
_ACCENT = (90, 130, 240)

_BANNER_TEXT = {
    "wifi_disconnected": "Wi-Fi disconnected",
    "alpaca_disconnected": "Alpaca disconnected",
    "update_available": "Update available",
}


class PygameRenderer:
    def __init__(self, size: tuple[int, int] | None = None) -> None:
        self._configured_size = size
        self._size = size or DEFAULT_SIZE
        self._screen: pygame.Surface | None = None
        self._font_large: pygame.font.Font | None = None
        self._font_medium: pygame.font.Font | None = None
        self._font_small: pygame.font.Font | None = None
        self._fb: FramebufferWriter | None = None

    def init(self) -> None:
        pygame.init()
        pygame.mouse.set_visible(False)

        fb_device = os.environ.get("MONSTRAPRO_FB_DEVICE")
        if fb_device:
            self._fb = FramebufferWriter(fb_device)
            self._size = self._configured_size or self._fb.detect_size()
            self._fb.open(*self._size)

        self._screen = pygame.display.set_mode(self._size)
        pygame.display.set_caption("Monstra.Pro Box")
        self._font_large = pygame.font.SysFont("arial", 40, bold=True)
        self._font_medium = pygame.font.SysFont("arial", 24)
        self._font_small = pygame.font.SysFont("arial", 18)

    def pump_events(self) -> bool:
        for event in pygame.event.get():
            if event.type == pygame.QUIT:
                return False
        return True

    def shutdown(self) -> None:
        if self._fb is not None:
            self._fb.close()
        pygame.quit()

    def _present(self) -> None:
        pygame.display.flip()
        if self._fb is not None:
            self._fb.write(self._require_screen())

    # -- screens --------------------------------------------------------

    def render_idle(
        self,
        snapshot: DisplaySnapshot,
        last_trade: LastTradeInfo | None,
        banner: str | None,
        *,
        local_pin: str | None = None,
    ) -> None:
        """idle_rotation.IdlePhase.PORTFOLIO - see render_idle_bot/
        render_idle_stock for the other two phases in the rotation."""
        screen = self._require_screen()
        screen.fill(_BG)
        # Top margin always reserves banner space, whether or not one is
        # showing this frame - otherwise content position jumps every time
        # a banner appears/clears, and a banner drawn on top of already-laid-out
        # content would overlap it (see the pre-fix render_preview.py screenshot).
        y = 20 + _BANNER_HEIGHT
        y = self._draw_header(screen, y, snapshot)
        y += 20
        y = self._draw_last_trade(screen, y, last_trade)
        y += 10
        self._draw_candles(screen, y, snapshot.candles, label="Performance")
        self._draw_local_access_footer(screen, local_pin)
        self._draw_banner(screen, banner)
        self._present()

    def render_idle_bot(self, view: BotView, banner: str | None, *, local_pin: str | None = None) -> None:
        """idle_rotation.IdlePhase.BOT - one active bot at a time, rotating
        (see display.idle_rotation / display.main._render_idle). No chart -
        only the portfolio screen keeps a candlestick; this shows every
        stock the bot currently signals plus the device's overall recent
        trade activity (not this bot's alone - see BotView's docstring on
        why per-bot attribution isn't available)."""
        screen = self._require_screen()
        screen.fill(_BG)
        y = 20 + _BANNER_HEIGHT

        name = view.display_name or view.bot_slug
        title = self._font_large.render(name, True, _FG)
        screen.blit(title, (20, y))
        y += 50

        signal_color = _YELLOW if view.latest_signal == "REBALANCE" else _MUTED
        signal_text = self._font_medium.render(view.latest_signal or "no signal yet", True, signal_color)
        screen.blit(signal_text, (20, y))
        y += 40

        # Split whatever's left between the two sections so neither one
        # (e.g. a bot signaling on 8+ symbols) starves the other out - see
        # image/README.md "What remains" for this panel's general
        # layout-tightness constraint at the real 480x320 resolution.
        footer_y = self._size[1] - _FOOTER_RESERVE
        midpoint = y + (footer_y - y) // 2
        y = self._draw_target_weights(screen, y, view.target_weights, max_y=midpoint)
        y += 10
        self._draw_recent_orders(screen, y, view.recent_orders, label="Recent activity (device-wide)", max_y=footer_y)
        self._draw_local_access_footer(screen, local_pin)
        self._draw_banner(screen, banner)
        self._present()

    def render_idle_stock(self, view: StockView, banner: str | None, *, local_pin: str | None = None) -> None:
        """idle_rotation.IdlePhase.STOCK - one (symbol, slide) combination at
        a time, rotating through the 5 tracked symbols x 3 slides (see
        display.idle_rotation / display.main._render_idle). view.slide_label
        ("Last hour"/"Last trading day"/"Last year") is the explicit timing
        reference the chart itself doesn't otherwise carry."""
        screen = self._require_screen()
        screen.fill(_BG)
        y = 20 + _BANNER_HEIGHT

        symbol_text = self._font_large.render(view.symbol, True, _FG)
        screen.blit(symbol_text, (20, y))
        y += 50

        if view.pct_change is not None:
            pct = view.pct_change * 100
            color = _GREEN if pct >= 0 else _RED
            move_text = self._font_medium.render(
                f"{'+' if pct >= 0 else ''}{pct:.2f}% ({view.slide_label.lower()})", True, color
            )
        else:
            move_text = self._font_medium.render("no chart data yet", True, _MUTED)
        screen.blit(move_text, (20, y))
        y += 40

        self._draw_candles(screen, y, view.candles, label=f"Price — {view.slide_label}")
        self._draw_local_access_footer(screen, local_pin)
        self._draw_banner(screen, banner)
        self._present()

    def render_wifi_setup(self, ap_ssid: str | None, setup_url: str | None, banner: str | None) -> None:
        screen = self._require_screen()
        screen.fill(_BG)
        width, height = self._size

        title = self._font_medium.render("Connect your phone to", True, _MUTED)
        screen.blit(title, title.get_rect(center=(width // 2, height // 2 - 70)))

        ssid = self._font_large.render(ap_ssid or "...", True, _ACCENT)
        screen.blit(ssid, ssid.get_rect(center=(width // 2, height // 2 - 20)))

        subtitle = self._font_medium.render("Then visit", True, _MUTED)
        screen.blit(subtitle, subtitle.get_rect(center=(width // 2, height // 2 + 30)))

        url_text = (setup_url or "").removeprefix("http://").removeprefix("https://") or "setup.monstra"
        url = self._font_medium.render(url_text, True, _FG)
        screen.blit(url, url.get_rect(center=(width // 2, height // 2 + 65)))

        self._draw_banner(screen, banner)
        self._present()

    def render_awaiting_activation(
        self, device_serial: str | None, pairing_code: str | None, banner: str | None
    ) -> None:
        screen = self._require_screen()
        screen.fill(_BG)
        width, height = self._size

        title = self._font_large.render("Activate this device", True, _FG)
        screen.blit(title, title.get_rect(center=(width // 2, height // 2 - 60)))

        subtitle = self._font_medium.render("Enter this code at monstra.pro", True, _MUTED)
        screen.blit(subtitle, subtitle.get_rect(center=(width // 2, height // 2 - 15)))

        # pairing_code is what actually goes into /dashboard/devices/pair -
        # device_serial is shown only as a small reference line underneath
        # (support calls, not something the owner ever types in). "..." is
        # this screen's existing placeholder for "not available yet" (see
        # render_wifi_setup's identical ap_ssid fallback) - covers the brief
        # window before HTTPActivationClient's first successful registration.
        code_text = pairing_code or "..."
        code = self._font_large.render(code_text, True, _ACCENT)
        screen.blit(code, code.get_rect(center=(width // 2, height // 2 + 50)))

        if device_serial:
            serial_text = self._font_small.render(device_serial, True, _MUTED)
            screen.blit(serial_text, serial_text.get_rect(center=(width // 2, height // 2 + 95)))

        self._draw_banner(screen, banner)
        self._present()

    def render_trade_wake(self, snapshot: DisplaySnapshot, banner: str | None) -> None:
        screen = self._require_screen()
        screen.fill(_BG)
        y = 20 + _BANNER_HEIGHT

        header = self._font_large.render("Trade executed", True, _GREEN)
        screen.blit(header, (20, y))
        y += 60

        y = self._draw_header(screen, y, snapshot)
        y += 20

        self._draw_recent_orders(
            screen, y, snapshot.recent_orders, label="Recent activity", max_y=self._size[1] - _FOOTER_RESERVE
        )

        self._draw_banner(screen, banner)
        self._present()

    # -- shared pieces ----------------------------------------------------

    def _require_screen(self) -> pygame.Surface:
        if self._screen is None:
            raise RuntimeError("PygameRenderer.init() must be called before rendering")
        return self._screen

    def _draw_header(self, screen: pygame.Surface, y: int, snapshot: DisplaySnapshot) -> int:
        equity_text = f"${snapshot.portfolio_equity:,.2f}" if snapshot.portfolio_equity is not None else "—"
        equity = self._font_large.render(equity_text, True, _FG)
        screen.blit(equity, (20, y))

        if snapshot.portfolio_pl_today is not None:
            pl = snapshot.portfolio_pl_today
            pl_color = _GREEN if pl >= 0 else _RED
            pl_text = self._font_medium.render(f"{'+' if pl >= 0 else ''}{pl:,.2f} today", True, pl_color)
            screen.blit(pl_text, (20, y + 46))

        market_text = "Market open" if snapshot.market_open else "Market closed"
        market_color = _GREEN if snapshot.market_open else _MUTED
        market = self._font_small.render(market_text, True, market_color)
        market_rect = market.get_rect(topright=(self._size[0] - 20, y))
        screen.blit(market, market_rect)

        sync_text = self._format_sync_time(snapshot.last_sync_at)
        sync = self._font_small.render(sync_text, True, _MUTED)
        sync_rect = sync.get_rect(topright=(self._size[0] - 20, y + 24))
        screen.blit(sync, sync_rect)

        return y + 70

    def _draw_target_weights(self, screen: pygame.Surface, y: int, target_weights: dict, *, max_y: int) -> int:
        """Every stock a bot currently signals (its full target-weights
        breakdown), largest allocation first - used only by render_idle_bot,
        which has no chart of its own (see BotView's docstring). Stops
        drawing at `max_y` (leaving room for whatever comes after, e.g.
        recent orders + the footer) rather than silently running off the
        bottom of the real 480x320 panel - shows a "+N more" line instead of
        just cutting off invisibly."""
        label = self._font_medium.render("Signals", True, _FG)
        screen.blit(label, (20, y))
        y += 26

        if not target_weights:
            text = self._font_small.render("no active allocation yet", True, _MUTED)
            screen.blit(text, (30, y))
            return y + 20

        items = sorted(target_weights.items(), key=lambda item: item[1], reverse=True)
        line_height = 18
        shown = 0
        for symbol, weight in items:
            if y + line_height > max_y:
                break
            line = f"{symbol:6s} {weight * 100:5.1f}%"
            text = self._font_small.render(line, True, _FG)
            screen.blit(text, (30, y))
            y += line_height
            shown += 1

        if shown < len(items) and y + line_height <= max_y:
            more = self._font_small.render(f"+{len(items) - shown} more", True, _MUTED)
            screen.blit(more, (30, y))
            y += line_height

        return y

    def _draw_recent_orders(self, screen: pygame.Surface, y: int, orders: list, *, label: str, max_y: int) -> int:
        """Shared by render_trade_wake and render_idle_bot - the device's
        most recent trades (already limited to 8 by the caller's query;
        this only ever takes the first 8 of whatever it's given as a second
        safety net). Stops at `max_y` for the same reason
        _draw_target_weights does."""
        label_surface = self._font_medium.render(label, True, _FG)
        screen.blit(label_surface, (20, y))
        y += 26

        if not orders:
            text = self._font_small.render("no trades yet", True, _MUTED)
            screen.blit(text, (30, y))
            return y + 20

        capped = orders[:8]
        line_height = 18
        shown = 0
        for order in capped:
            if y + line_height > max_y:
                break
            color = _GREEN if order["side"] == "buy" else _RED
            line = f"{order['side'].upper():4s} {order['symbol']:6s} ${order['notional'] or 0:,.2f}  [{order['status']}]"
            text = self._font_small.render(line, True, color)
            screen.blit(text, (30, y))
            y += line_height
            shown += 1

        if shown < len(capped) and y + line_height <= max_y:
            more = self._font_small.render(f"+{len(capped) - shown} more", True, _MUTED)
            screen.blit(more, (30, y))
            y += line_height

        return y

    def _draw_last_trade(self, screen: pygame.Surface, y: int, last_trade: LastTradeInfo | None) -> int:
        if last_trade is None:
            text = self._font_small.render("no trades yet", True, _MUTED)
            screen.blit(text, (20, y))
            return y + 24

        side_word = "Bought" if last_trade.side == "buy" else "Sold"
        line = f"Last: {side_word} {last_trade.symbol}"
        color = _FG
        if last_trade.unrealized_plpc is not None:
            pct = last_trade.unrealized_plpc * 100
            color = _GREEN if pct >= 0 else _RED
            line += f"  {'+' if pct >= 0 else ''}{pct:.2f}%"

        text = self._font_small.render(line, True, color)
        screen.blit(text, (20, y))
        return y + 24

    @staticmethod
    def _format_span(span: timedelta) -> str:
        """A human-readable "how much history is this" caption - the actual
        gap this addresses: candles alone don't say whether they're 5
        minutes or 5 months apart."""
        total_seconds = span.total_seconds()
        if total_seconds < 3600:
            return f"{max(1, int(total_seconds // 60))}m"
        if total_seconds < 86400:
            return f"{total_seconds / 3600:.1f}h"
        days = total_seconds / 86400
        if days < 60:
            return f"{days:.0f}d"
        return f"{days / 30:.0f}mo"

    def _draw_candles(self, screen: pygame.Surface, y: int, candles: list[Candle], *, label: str) -> int:
        """Renders any (ts, value) series already bucketed/fetched into
        candles by display.candles.build_candles or display.stock_view - see
        those modules for how each candle's timespan is decided. Pure
        drawing: no bucketing/aggregation happens here, only pixel mapping.
        `label` distinguishes what's being shown (account "Performance", a
        stock's "Price — Last hour") since idle_rotation cycles this same
        drawing routine across multiple data sources. Always captions the
        total visible time span underneath - the actual reference point the
        chart itself doesn't otherwise carry (owner feedback: "no reference
        to what they represent timing wise")."""
        label_surface = self._font_medium.render(label, True, _FG)
        screen.blit(label_surface, (20, y))
        y += 30

        chart_left, chart_right = 20, self._size[0] - 20
        chart_width = chart_right - chart_left

        if len(candles) < 2:
            text = self._font_small.render("not enough data yet", True, _MUTED)
            screen.blit(text, (30, y))
            return y + _CHART_HEIGHT

        lo = min(c.low for c in candles)
        hi = max(c.high for c in candles)
        if hi == lo:
            hi = lo + 1  # a perfectly flat account (e.g. market closed) still needs a drawable range

        def y_for(value: float) -> int:
            ratio = (value - lo) / (hi - lo)
            return y + _CHART_HEIGHT - int(ratio * _CHART_HEIGHT)

        slot_width = chart_width / len(candles)
        body_width = max(2, int(slot_width * 0.6))

        for i, candle in enumerate(candles):
            cx = int(chart_left + slot_width * (i + 0.5))
            color = _GREEN if candle.close >= candle.open else _RED

            pygame.draw.line(screen, color, (cx, y_for(candle.high)), (cx, y_for(candle.low)), 1)

            open_y, close_y = y_for(candle.open), y_for(candle.close)
            top, bottom = min(open_y, close_y), max(open_y, close_y)
            if bottom == top:
                bottom = top + 1  # a doji (open == close) still needs a visible mark
            pygame.draw.rect(screen, color, pygame.Rect(cx - body_width // 2, top, body_width, bottom - top))

        span = candles[-1].bucket_start - candles[0].bucket_start
        caption = f"{len(candles)} candles, last {self._format_span(span)}" if span.total_seconds() > 0 else f"{len(candles)} candles"
        caption_surface = self._font_small.render(caption, True, _MUTED)
        screen.blit(caption_surface, (chart_left, y + _CHART_HEIGHT + 2))

        return y + _CHART_HEIGHT + 20

    def _draw_local_access_footer(self, screen: pygame.Surface, local_pin: str | None) -> None:
        """A persistent, small reminder of how to reach
        services/portfolio_web's local page (Objectives: edit the
        portfolio from the "wifi site") - shown on all three idle-rotation
        sub-screens, not just one, since the owner might want it regardless
        of which phase happens to be showing. Bottom-anchored via
        get_rect(bottomleft=...) rather than flowing after the content
        above, so it never needs to know how tall that content was."""
        if not local_pin:
            return
        width, height = self._size
        text = f"monstrapro.local   PIN {local_pin}"
        surface = self._font_small.render(text, True, _MUTED)
        screen.blit(surface, surface.get_rect(bottomleft=(20, height - 8)))

    def _draw_banner(self, screen: pygame.Surface, banner: str | None) -> None:
        if banner is None:
            return
        width, _ = self._size
        rect = pygame.Rect(0, 0, width, 36)
        pygame.draw.rect(screen, _BANNER_BG, rect)
        text = self._font_small.render(_BANNER_TEXT.get(banner, banner), True, _FG)
        screen.blit(text, text.get_rect(center=rect.center))

    @staticmethod
    def _format_sync_time(ts: datetime | None) -> str:
        if ts is None:
            return "never synced"
        age = datetime.now(timezone.utc) - as_utc(ts)
        minutes = int(age.total_seconds() // 60)
        if minutes < 1:
            return "synced just now"
        if minutes < 60:
            return f"synced {minutes}m ago"
        return f"synced {minutes // 60}h ago"
