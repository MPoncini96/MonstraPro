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
800x480 dev-window default below.

The three idle-rotation screens (render_idle/render_idle_bot/render_idle_stock)
compute a `compact` flag from actual screen height (< 400px) and switch to
tighter chart heights and section gaps in that case, rather than assuming
the spacious 800x480 dev-window default - the real 480x320 panel has only
~236px of usable vertical space once the banner/footer reserves are
subtracted, not enough to lay out every element at dev-window spacing.
Text size itself is never reduced for this - only whitespace and chart
height flex, per the design brief ("if information feels crowded, move it
to another slide rather than shrinking text"). There is nowhere else to
move it to within a single screen, so compact spacing is the next-best
option; verified by headless render at both sizes during development
(SDL_VIDEODRIVER=dummy + pygame.image.save), the same technique that caught
the original timezone/banner-overlap bugs.
"""

from __future__ import annotations

import os
from datetime import datetime, timedelta, timezone

import pygame

from display.bot_view import BotView, LatestAction
from display.candles import Candle
from display.framebuffer import FramebufferWriter
from display.last_trade import LastTradeInfo
from display.snapshot import DisplaySnapshot, as_utc
from display.stock_view import StockView

DEFAULT_SIZE = (800, 480)
_BANNER_HEIGHT = 36
_CHART_HEIGHT = 70
_CHART_HEIGHT_COMPACT = 42
_FOOTER_RESERVE = 28
_MARGIN = 20
_COMPACT_HEIGHT_THRESHOLD = 400  # real panel is 320; dev window is 480

# One purpose per screen, one palette across all of them (design brief):
# white for titles/values/tickers, green/red for buy-or-gain / sell-or-loss,
# yellow for rebalance/pending/warnings, blue for informational status,
# gray for footer/secondary text. No other colors are introduced anywhere
# below.
_BG = (12, 14, 20)
_FG = (230, 232, 238)
_MUTED = (140, 145, 156)
_GREEN = (60, 200, 120)
_RED = (220, 80, 90)
_YELLOW = (230, 190, 60)
_BLUE = (90, 130, 240)
_BANNER_BG = (120, 40, 40)

_STATUS_COLORS = {
    "REBALANCING": _YELLOW,
    "BUYING": _GREEN,
    "SELLING": _RED,
    "WAITING": _BLUE,
    "IDLE": _MUTED,
}

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

    def _is_compact(self) -> bool:
        return self._size[1] < _COMPACT_HEIGHT_THRESHOLD

    # -- screens --------------------------------------------------------

    def render_idle(
        self,
        snapshot: DisplaySnapshot,
        last_trade: LastTradeInfo | None,
        banner: str | None,
        *,
        local_pin: str | None = None,
    ) -> None:
        """idle_rotation.IdlePhase.PORTFOLIO - "How is my portfolio doing?"
        Portfolio value is the dominant element; performance chart, largest
        positions, and biggest movers are all secondary and stay compact so
        the value remains the focal point. `last_trade` is accepted for
        Renderer protocol stability but not drawn here - see
        render_idle_bot's "Latest Action" for where a single bot's own
        latest decision is shown instead; this screen's per-symbol
        "Biggest Movers" covers "what's moving" at the portfolio level."""
        screen = self._require_screen()
        screen.fill(_BG)
        compact = self._is_compact()
        # Top margin always reserves banner space, whether or not one is
        # showing this frame - otherwise content position jumps every time
        # a banner appears/clears, and a banner drawn on top of already-laid-out
        # content would overlap it (see the pre-fix render_preview.py screenshot).
        y = _MARGIN + _BANNER_HEIGHT
        y = self._draw_header(screen, y, snapshot)
        y += 12 if compact else 20

        chart_height = _CHART_HEIGHT_COMPACT if compact else _CHART_HEIGHT
        y = self._draw_candles(screen, y, snapshot.candles, label="Performance", height=chart_height)
        y += 8 if compact else 16

        self._draw_portfolio_lists(screen, y, snapshot)
        self._draw_local_access_footer(screen, local_pin)
        self._draw_banner(screen, banner)
        self._present()

    def render_idle_bot(self, view: BotView, banner: str | None, *, local_pin: str | None = None) -> None:
        """idle_rotation.IdlePhase.BOT - "What is this algorithm doing?"
        One active bot at a time, rotating (see display.idle_rotation /
        display.main._render_idle). Shows this bot's name, algorithm
        family, current status, its full target allocation, and its own
        latest rebalance decision (see BotView's docstring for why that's
        not an executed dollar trade)."""
        screen = self._require_screen()
        screen.fill(_BG)
        compact = self._is_compact()
        y = _MARGIN + _BANNER_HEIGHT

        name = view.display_name or view.bot_slug
        title = self._font_large.render(name, True, _FG)
        screen.blit(title, (_MARGIN, y))
        y += 44 if compact else 50

        # Algorithm family + current status share one line - two short
        # facts about "what kind of bot is this and what's it doing", not
        # two separate topics - freeing a full line's worth of height for
        # the target-allocation list below, which is this screen's main
        # content.
        status_x = _MARGIN
        if view.algorithm_family:
            family_surface = self._font_small.render(view.algorithm_family, True, _MUTED)
            screen.blit(family_surface, (_MARGIN, y + 6))
            status_x = _MARGIN + family_surface.get_width() + 14
        status_color = _STATUS_COLORS.get(view.status, _MUTED)
        status_surface = self._font_medium.render(view.status, True, status_color)
        screen.blit(status_surface, (status_x, y))
        y += 34 if compact else 40

        footer_y = self._size[1] - _FOOTER_RESERVE
        # Reserve room for "Latest Action" (label + one "BUY SYMBOL
        # Pending" line, ~54px) below the allocation list so a bot with
        # many symbols can't push it off-screen - same reasoning the old
        # device-wide activity/target-weights split used.
        action_reserve = 70 if compact else 82
        weights_max_y = footer_y - action_reserve
        y = self._draw_target_weights(screen, y, view.target_weights, max_y=weights_max_y)
        y = max(y, weights_max_y) + (10 if compact else 16)

        self._draw_latest_action(screen, y, view.latest_action)
        self._draw_local_access_footer(screen, local_pin)
        self._draw_banner(screen, banner)
        self._present()

    def render_idle_stock(self, view: StockView, banner: str | None, *, local_pin: str | None = None) -> None:
        """idle_rotation.IdlePhase.STOCK - "What is happening with this
        stock?" One (symbol, slide) combination at a time, rotating through
        the tracked symbols x 3 slides (see display.idle_rotation /
        display.main._render_idle). view.slide_label ("Last hour"/"Last
        trading day"/"Last year") is the explicit timing reference the
        chart itself doesn't otherwise carry."""
        screen = self._require_screen()
        screen.fill(_BG)
        compact = self._is_compact()
        y = _MARGIN + _BANNER_HEIGHT

        symbol_text = self._font_large.render(view.symbol, True, _FG)
        screen.blit(symbol_text, (_MARGIN, y))
        y += 44 if compact else 50

        # Current allocation and today's move are two short, related facts
        # about where this stock stands right now - one line, not two, so
        # the chart and "Owned By" keep most of the room.
        segments: list[tuple[str, tuple[int, int, int]]] = []
        if view.portfolio_weight is not None:
            segments.append((f"{view.portfolio_weight * 100:.0f}% of portfolio", _FG))
        else:
            segments.append(("not currently held", _MUTED))
        if view.pct_change is not None:
            pct = view.pct_change * 100
            color = _GREEN if pct >= 0 else _RED
            segments.append((f"   {'+' if pct >= 0 else ''}{pct:.2f}% {view.slide_label.lower()}", color))
        else:
            segments.append(("   no chart data yet", _MUTED))
        self._draw_inline_segments(screen, _MARGIN, y, segments, self._font_medium)
        y += 34 if compact else 40

        chart_height = _CHART_HEIGHT_COMPACT if compact else _CHART_HEIGHT
        y = self._draw_candles(screen, y, view.candles, label=f"Price — {view.slide_label}", height=chart_height)
        y += 8 if compact else 16

        self._draw_owned_by(screen, y, view.owned_by, max_y=self._size[1] - _FOOTER_RESERVE)
        self._draw_local_access_footer(screen, local_pin)
        self._draw_banner(screen, banner)
        self._present()

    def render_wifi_setup(self, ap_ssid: str | None, setup_url: str | None, banner: str | None) -> None:
        screen = self._require_screen()
        screen.fill(_BG)
        width, height = self._size

        title = self._font_medium.render("Connect your phone to", True, _MUTED)
        screen.blit(title, title.get_rect(center=(width // 2, height // 2 - 70)))

        ssid = self._font_large.render(ap_ssid or "...", True, _BLUE)
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
        code = self._font_large.render(code_text, True, _BLUE)
        screen.blit(code, code.get_rect(center=(width // 2, height // 2 + 50)))

        if device_serial:
            serial_text = self._font_small.render(device_serial, True, _MUTED)
            screen.blit(serial_text, serial_text.get_rect(center=(width // 2, height // 2 + 95)))

        self._draw_banner(screen, banner)
        self._present()

    def render_trade_wake(self, snapshot: DisplaySnapshot, banner: str | None) -> None:
        screen = self._require_screen()
        screen.fill(_BG)
        y = _MARGIN + _BANNER_HEIGHT

        header = self._font_large.render("Trade executed", True, _GREEN)
        screen.blit(header, (_MARGIN, y))
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
        screen.blit(equity, (_MARGIN, y))

        if snapshot.portfolio_pl_today is not None:
            pl = snapshot.portfolio_pl_today
            pl_color = _GREEN if pl >= 0 else _RED
            pl_text = self._font_medium.render(f"{'+' if pl >= 0 else ''}{pl:,.2f} today", True, pl_color)
            screen.blit(pl_text, (_MARGIN, y + 46))

        market_text = "Market open" if snapshot.market_open else "Market closed"
        market_color = _GREEN if snapshot.market_open else _MUTED
        market = self._font_small.render(market_text, True, market_color)
        market_rect = market.get_rect(topright=(self._size[0] - _MARGIN, y))
        screen.blit(market, market_rect)

        sync_text = self._format_sync_time(snapshot.last_sync_at)
        sync = self._font_small.render(sync_text, True, _MUTED)
        sync_rect = sync.get_rect(topright=(self._size[0] - _MARGIN, y + 24))
        screen.blit(sync, sync_rect)

        return y + 70

    def _draw_inline_segments(
        self, screen: pygame.Surface, x: int, y: int, segments: list[tuple[str, tuple[int, int, int]]], font
    ) -> int:
        cursor_x = x
        for text, color in segments:
            surface = font.render(text, True, color)
            screen.blit(surface, (cursor_x, y))
            cursor_x += surface.get_width()
        return cursor_x

    def _draw_target_weights(self, screen: pygame.Surface, y: int, target_weights: dict, *, max_y: int) -> int:
        """This bot's full target-weights breakdown, largest allocation
        first - the main content of the bot screen. Same font/row-pitch as
        the portfolio screen's Largest Positions / Biggest Movers lists,
        for a consistent size tier across every compact list in the app.
        Stops drawing at `max_y` (leaving room for whatever comes after,
        e.g. Latest Action + the footer) rather than silently running off
        the bottom of the real 480x320 panel - shows a "+N more" line
        instead of just cutting off invisibly."""
        if not target_weights:
            text = self._font_small.render("no active allocation yet", True, _MUTED)
            screen.blit(text, (_MARGIN, y))
            return y + 20

        items = sorted(target_weights.items(), key=lambda item: item[1], reverse=True)
        line_height = 24
        available_rows = max(0, (max_y - y) // line_height)
        # Reserve a row for "+N more" up front rather than discovering
        # after the fact that there's no room left to say anything was
        # truncated - but only when there's more than one row of room to
        # begin with, or "0 items shown, +N more" wastes the one row that
        # could have shown real content instead.
        if len(items) <= available_rows:
            rows_to_draw, remaining = items, 0
        elif available_rows >= 2:
            rows_to_draw = items[: available_rows - 1]
            remaining = len(items) - len(rows_to_draw)
        else:
            rows_to_draw, remaining = items[:available_rows], 0

        for symbol, weight in rows_to_draw:
            symbol_surface = self._font_small.render(symbol, True, _FG)
            screen.blit(symbol_surface, (_MARGIN, y))
            weight_surface = self._font_small.render(f"{weight * 100:.0f}%", True, _FG)
            screen.blit(weight_surface, weight_surface.get_rect(topright=(self._size[0] - _MARGIN, y)))
            y += line_height

        if remaining > 0:
            more = self._font_small.render(f"+{remaining} more", True, _MUTED)
            screen.blit(more, (_MARGIN, y))
            y += 20

        return y

    def _draw_latest_action(self, screen: pygame.Surface, y: int, action: LatestAction | None) -> int:
        """This bot's own most recent rebalance decision - see BotView's
        docstring for why there is no dollar amount attached. Side/symbol
        and Pending/Completed share one line (mixed font sizes, same
        baseline) rather than three full lines, so this section's total
        height stays predictable regardless of screen size."""
        label = self._font_small.render("Latest Action", True, _MUTED)
        screen.blit(label, (_MARGIN, y))
        y += 24

        if action is None:
            text = self._font_small.render("no recent action", True, _MUTED)
            screen.blit(text, (_MARGIN, y))
            return y + 20

        side_color = _GREEN if action.side == "buy" else _RED
        action_surface = self._font_medium.render(f"{action.side.upper()} {action.symbol}", True, side_color)
        screen.blit(action_surface, (_MARGIN, y))

        status_color = _YELLOW if action.status == "Pending" else _MUTED
        status_surface = self._font_small.render(action.status, True, status_color)
        status_x = _MARGIN + action_surface.get_width() + 14
        # Vertically center the smaller status word against the medium
        # action text rather than aligning both to the same top y.
        status_y = y + (action_surface.get_height() - status_surface.get_height()) // 2
        screen.blit(status_surface, (status_x, status_y))
        return y + 30

    def _draw_portfolio_lists(self, screen: pygame.Surface, y: int, snapshot: DisplaySnapshot) -> None:
        """Largest Positions and Biggest Movers side by side rather than
        stacked - both are capped to a handful of rows (2 and 3
        respectively, see snapshot.build_snapshot), so a two-column band
        costs only as much vertical space as the taller of the two lists,
        keeping the portfolio value above as the clear focal point."""
        width, height = self._size
        footer_y = height - _FOOTER_RESERVE
        col_gap = 24
        col_width = (width - 2 * _MARGIN - col_gap) // 2
        left_x = _MARGIN
        right_x = left_x + col_width + col_gap

        position_rows = [
            (p.symbol, f"{p.weight * 100:.0f}%", _FG) for p in snapshot.largest_positions
        ]
        mover_rows = [
            (
                m.symbol,
                f"{'+' if m.pct_change_today >= 0 else ''}{m.pct_change_today * 100:.1f}%",
                _GREEN if m.pct_change_today >= 0 else _RED,
            )
            for m in snapshot.biggest_movers
        ]

        self._draw_compact_list(
            screen, left_x, y, col_width, footer_y,
            title="Largest Positions", rows=position_rows, empty_text="no positions yet",
        )
        self._draw_compact_list(
            screen, right_x, y, col_width, footer_y,
            title="Biggest Movers", rows=mover_rows, empty_text="no movers yet",
        )

    def _draw_compact_list(
        self,
        screen: pygame.Surface,
        x: int,
        y: int,
        col_width: int,
        max_y: int,
        *,
        title: str,
        rows: list[tuple[str, str, tuple[int, int, int]]],
        empty_text: str,
    ) -> None:
        label = self._font_small.render(title, True, _MUTED)
        screen.blit(label, (x, y))
        y += 24

        if not rows:
            text = self._font_small.render(empty_text, True, _MUTED)
            screen.blit(text, (x, y))
            return

        line_height = 22
        for symbol, value_text, color in rows:
            if y + line_height > max_y:
                break
            symbol_surface = self._font_small.render(symbol, True, _FG)
            screen.blit(symbol_surface, (x, y))
            value_surface = self._font_small.render(value_text, True, color)
            screen.blit(value_surface, value_surface.get_rect(topright=(x + col_width, y)))
            y += line_height

    def _draw_owned_by(self, screen: pygame.Surface, y: int, owned_by: list[str], *, max_y: int) -> None:
        """"Owned By" lists each active bot currently targeting this
        symbol; once there are more than a handful - or simply not enough
        room left above the footer to list them - naming each one stops
        being glanceable, so a count takes over instead (matches the design
        brief's own two examples for this section)."""
        if not owned_by:
            text = self._font_small.render("not currently held by any bot", True, _MUTED)
            screen.blit(text, (_MARGIN, y))
            return

        label_height, row_height = 26, 30
        fits = y + label_height + row_height * len(owned_by) <= max_y
        if len(owned_by) > 3 or not fits:
            label = self._font_medium.render(f"Active in {len(owned_by)} Bots", True, _FG)
            screen.blit(label, (_MARGIN, y))
            return

        label = self._font_small.render("Owned By", True, _MUTED)
        screen.blit(label, (_MARGIN, y))
        y += label_height
        for name in owned_by:
            text = self._font_medium.render(name, True, _FG)
            screen.blit(text, (_MARGIN, y))
            y += row_height

    def _draw_recent_orders(self, screen: pygame.Surface, y: int, orders: list, *, label: str, max_y: int) -> int:
        """Used only by render_trade_wake now - the idle bot screen shows
        this bot's own Latest Action instead (see BotView's docstring on
        why device-wide activity was replaced there)."""
        label_surface = self._font_medium.render(label, True, _FG)
        screen.blit(label_surface, (_MARGIN, y))
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

    def _draw_candles(
        self, screen: pygame.Surface, y: int, candles: list[Candle], *, label: str, height: int = _CHART_HEIGHT
    ) -> int:
        """Renders any (ts, value) series already bucketed/fetched into
        candles by display.candles.build_candles or display.stock_view - see
        those modules for how each candle's timespan is decided. Pure
        drawing: no bucketing/aggregation happens here, only pixel mapping.
        `label` distinguishes what's being shown (account "Performance", a
        stock's "Price — Last hour") since idle_rotation cycles this same
        drawing routine across multiple data sources. `height` shrinks on
        the real 480x320 panel (see module docstring) - the chart is a
        visual, not text, so it's what flexes before anything gets
        crowded. Always captions the total visible time span underneath -
        the actual reference point the chart itself doesn't otherwise
        carry (owner feedback: "no reference to what they represent timing
        wise")."""
        label_surface = self._font_medium.render(label, True, _FG)
        screen.blit(label_surface, (_MARGIN, y))
        y += 30

        chart_left, chart_right = _MARGIN, self._size[0] - _MARGIN
        chart_width = chart_right - chart_left

        if len(candles) < 2:
            text = self._font_small.render("not enough data yet", True, _MUTED)
            screen.blit(text, (30, y))
            return y + height

        lo = min(c.low for c in candles)
        hi = max(c.high for c in candles)
        if hi == lo:
            hi = lo + 1  # a perfectly flat account (e.g. market closed) still needs a drawable range

        def y_for(value: float) -> int:
            ratio = (value - lo) / (hi - lo)
            return y + height - int(ratio * height)

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
        screen.blit(caption_surface, (chart_left, y + height + 2))

        return y + height + 20

    def _draw_local_access_footer(self, screen: pygame.Surface, local_pin: str | None) -> None:
        """A persistent, small reminder of how to reach
        services/portfolio_web's local page (Objectives: edit the
        portfolio from the "wifi site") - shown on all three idle-rotation
        sub-screens, not just one, since the owner might want it regardless
        of which phase happens to be showing. Bottom-anchored via
        get_rect(bottomleft=...) rather than flowing after the content
        above, so it never needs to know how tall that content was. Small
        and muted by design - it must never compete with the main content."""
        if not local_pin:
            return
        width, height = self._size
        text = f"monstrapro.local   PIN {local_pin}"
        surface = self._font_small.render(text, True, _MUTED)
        screen.blit(surface, surface.get_rect(bottomleft=(_MARGIN, height - 8)))

    def _draw_banner(self, screen: pygame.Surface, banner: str | None) -> None:
        if banner is None:
            return
        width, _ = self._size
        rect = pygame.Rect(0, 0, width, _BANNER_HEIGHT)
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
