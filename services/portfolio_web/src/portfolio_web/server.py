"""Always-on local portfolio-editing page. Unlike device_agent's setup
page - which only exists during first-boot Wi-Fi onboarding and is torn
down once the device joins a network - this service stays up so the owner
can revisit http://monstrapro.local anytime from a browser on the same
home network. PIN-gated (auth.py) so not just anyone on the network can
change trading behavior.

Stdlib-only (http.server), same "minimal dependencies" principle as
device_agent/setup_server.py.
"""

from __future__ import annotations

import logging
import threading
from http import cookies
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs

from device_core.core import DeviceCore
from strategy_engine.registry import ALGORITHM_REGISTRY

from portfolio_web.auth import SESSION_COOKIE_NAME, SessionStore, verify_pin
from portfolio_web.pages import render_login_page, render_portfolio_page

logger = logging.getLogger(__name__)


def _session_token(handler: BaseHTTPRequestHandler) -> str | None:
    raw = handler.headers.get("Cookie")
    if not raw:
        return None
    jar = cookies.SimpleCookie()
    jar.load(raw)
    morsel = jar.get(SESSION_COOKIE_NAME)
    return morsel.value if morsel else None


def _read_form(handler: BaseHTTPRequestHandler) -> dict[str, list[str]]:
    length = int(handler.headers.get("Content-Length", "0"))
    body = handler.rfile.read(length).decode("utf-8")
    return parse_qs(body)


def _bots_view(core: DeviceCore) -> list[dict]:
    active_slugs = {row["bot_slug"] for row in core.strategies.get_active()}
    return [
        {"slug": entry.slug, "display_name": entry.display_name, "is_active": entry.slug in active_slugs}
        for entry in ALGORITHM_REGISTRY
    ]


def make_handler(core: DeviceCore, sessions: SessionStore):
    class PortfolioHandler(BaseHTTPRequestHandler):
        server_version = "MonstraProPortfolio/1.0"

        def log_message(self, format: str, *args) -> None:  # noqa: A002 - stdlib override signature
            pass  # a failed /login POST body carries the attempted PIN - never log request lines

        def _write_html(self, status: int, body: bytes, *, set_cookie: str | None = None) -> None:
            self.send_response(status)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            if set_cookie:
                self.send_header("Set-Cookie", set_cookie)
            self.end_headers()
            self.wfile.write(body)

        def _redirect(self, location: str, *, set_cookie: str | None = None) -> None:
            self.send_response(303)
            self.send_header("Location", location)
            if set_cookie:
                self.send_header("Set-Cookie", set_cookie)
            self.end_headers()

        def _authenticated(self) -> bool:
            return sessions.is_valid(_session_token(self))

        def _portfolio_page(self, *, status: int = 200, message: str | None = None) -> None:
            body = render_portfolio_page(bots=_bots_view(core), holdings=core.manual_holdings.list_all(), message=message)
            self._write_html(status, body)

        def do_GET(self) -> None:  # noqa: N802 - stdlib override signature
            if self.path in ("/", "/login"):
                if self._authenticated():
                    self._redirect("/portfolio")
                    return
                self._write_html(200, render_login_page())
                return

            if self.path == "/portfolio":
                if not self._authenticated():
                    self._redirect("/")
                    return
                self._portfolio_page()
                return

            if self.path == "/logout":
                sessions.invalidate(_session_token(self))
                self._redirect("/", set_cookie=f"{SESSION_COOKIE_NAME}=; Path=/; Max-Age=0")
                return

            self.send_response(404)
            self.end_headers()

        def do_POST(self) -> None:  # noqa: N802 - stdlib override signature
            if self.path == "/login":
                fields = _read_form(self)
                submitted = (fields.get("pin") or [""])[0]
                pin = core.devices.get_or_create_local_pin()
                if verify_pin(submitted, pin):
                    token = sessions.create()
                    self._redirect("/portfolio", set_cookie=f"{SESSION_COOKIE_NAME}={token}; Path=/; HttpOnly")
                    return
                self._write_html(401, render_login_page(error="Incorrect PIN."))
                return

            if not self._authenticated():
                self._redirect("/")
                return

            if self.path == "/portfolio/bots":
                fields = _read_form(self)
                selected = set(fields.get("bot") or [])
                for entry in ALGORITHM_REGISTRY:
                    core.strategies.upsert(
                        bot_slug=entry.slug,
                        display_name=entry.display_name,
                        is_active=entry.slug in selected,
                        source="local",
                    )
                self._redirect("/portfolio")
                return

            if self.path == "/portfolio/holdings/add":
                fields = _read_form(self)
                symbol = (fields.get("symbol") or [""])[0].strip().upper()
                qty_raw = (fields.get("target_qty") or [""])[0]
                try:
                    qty = float(qty_raw)
                    if not symbol or qty <= 0:
                        raise ValueError("symbol and a positive quantity are required")
                    core.manual_holdings.add(symbol=symbol, target_qty=qty)
                except ValueError:
                    self._portfolio_page(status=400, message="Enter a symbol and a positive quantity.")
                    return
                self._redirect("/portfolio")
                return

            if self.path == "/portfolio/holdings/remove":
                fields = _read_form(self)
                symbol = (fields.get("symbol") or [""])[0].strip().upper()
                if symbol:
                    core.manual_holdings.remove(symbol)
                self._redirect("/portfolio")
                return

            self.send_response(404)
            self.end_headers()

    return PortfolioHandler


class PortfolioServer:
    """`port=0` binds an OS-assigned ephemeral port - used by tests so they
    never need a fixed port or elevated privileges, on any OS including
    Windows. The real device binds port 80 (see
    image/systemd/monstrapro-portfolio-web.service's
    AmbientCapabilities=CAP_NET_BIND_SERVICE, so this runs as the non-root
    `monstrapro` user without needing full root)."""

    def __init__(self, core: DeviceCore, sessions: SessionStore, *, host: str = "0.0.0.0", port: int = 80) -> None:
        handler = make_handler(core, sessions)
        self._httpd = ThreadingHTTPServer((host, port), handler)
        self._thread = threading.Thread(target=self._httpd.serve_forever, daemon=True)

    @property
    def port(self) -> int:
        return self._httpd.server_address[1]

    def start(self) -> None:
        self._thread.start()

    def stop(self) -> None:
        self._httpd.shutdown()
        self._httpd.server_close()
