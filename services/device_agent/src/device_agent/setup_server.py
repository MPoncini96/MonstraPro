"""Minimal local HTTP setup page (Objectives.txt step 4): a customer joined
to the temporary onboarding access point visits setup.monstra and gets one
HTML page listing nearby Wi-Fi networks with a form to submit ssid+password.
`setup.monstra` resolving to the AP's own address is a DNS-layer concern
handled by the hotspot's dnsmasq config, not this module - see
image/config/dnsmasq-setup-domain.conf and image/README.md.

Deliberately stdlib-only (`http.server`), matching ARCHITECTURE.md's
"minimal dependencies" principle - this page is shown for at most a few
minutes during first boot, not a general-purpose web app, and
ARCHITECTURE.md section 9's "no local HTTP API in V1" is scoped to
*ongoing* device configuration, which stays true; this is a one-time,
first-boot-only exception, documented here and in image/README.md.

Submitted credentials go straight into an in-memory queue that
onboarding.py drains and hands to NetworkManager. They are never logged
(the request handler suppresses its own access log, since a misbehaving
client could in principle put a password in a query string), never written
to disk by this module, and never reach any Monstra server - see
image/README.md "local-credentials architecture".
"""

from __future__ import annotations

import html
import queue
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs

from device_agent.network import WifiScanner
from device_agent.onboarding import SubmittedCredentials

PAGE_TITLE = "Monstra Pro Setup"

_STYLE = """
body { font-family: sans-serif; max-width: 420px; margin: 2rem auto; padding: 0 1rem; }
.error { color: #b00020; }
label { display: block; margin-top: 1rem; }
select, input, button { width: 100%; padding: 0.5rem; margin-top: 0.25rem; box-sizing: border-box; }
button { margin-top: 1.5rem; cursor: pointer; }
"""


def render_form_page(networks: list, *, error: str | None = None) -> bytes:
    options = "".join(
        f'<option value="{html.escape(n.ssid)}">{html.escape(n.ssid)} '
        f'({"secured" if n.secured else "open"}, {n.signal}%)</option>'
        for n in networks
    )
    error_html = f'<p class="error">{html.escape(error)}</p>' if error else ""
    return (
        f"<!doctype html><html><head><meta charset=\"utf-8\">"
        f'<meta name="viewport" content="width=device-width, initial-scale=1">'
        f"<title>{PAGE_TITLE}</title><style>{_STYLE}</style></head><body>"
        f"<h1>Connect Monstra Pro to Wi-Fi</h1>"
        f"<p>Select your Wi-Fi network and enter its password. "
        f"This never leaves your device.</p>"
        f"{error_html}"
        f'<form method="post" action="/connect">'
        f'<label>Network<select name="ssid">{options}</select></label>'
        f'<label>Password<input type="password" name="password" autocomplete="off"></label>'
        f'<button type="submit">Connect</button>'
        f"</form></body></html>"
    ).encode("utf-8")


def render_submitted_page() -> bytes:
    return (
        f"<!doctype html><html><head><meta charset=\"utf-8\"><title>{PAGE_TITLE}</title></head>"
        f"<body><h1>Connecting...</h1>"
        f"<p>Monstra Pro is joining your Wi-Fi network. You can close this page.</p>"
        f"</body></html>"
    ).encode("utf-8")


def _make_handler(scanner: WifiScanner, submissions: "queue.Queue[SubmittedCredentials]"):
    class SetupHandler(BaseHTTPRequestHandler):
        server_version = "MonstraProSetup/1.0"

        def log_message(self, format: str, *args) -> None:  # noqa: A002 - stdlib override signature
            pass  # never write request lines (may contain a submitted password) to stderr/journald

        def _write(self, status: int, body: bytes) -> None:
            self.send_response(status)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def do_GET(self) -> None:  # noqa: N802 - stdlib override signature
            if self.path not in ("/", "/index.html"):
                self.send_response(404)
                self.end_headers()
                return
            self._write(200, render_form_page(scanner.scan()))

        def do_POST(self) -> None:  # noqa: N802 - stdlib override signature
            if self.path != "/connect":
                self.send_response(404)
                self.end_headers()
                return
            length = int(self.headers.get("Content-Length", "0"))
            fields = parse_qs(self.rfile.read(length).decode("utf-8"))
            ssid = (fields.get("ssid") or [""])[0].strip()
            password = (fields.get("password") or [""])[0] or None
            if not ssid:
                self._write(400, render_form_page(scanner.scan(), error="Please choose a network."))
                return
            submissions.put(SubmittedCredentials(ssid=ssid, password=password))
            self._write(200, render_submitted_page())

    return SetupHandler


class SetupServer:
    """Runs the setup page in a background thread. Implements
    onboarding.SetupSubmissionSource directly (`.poll()`), so one instance
    serves both roles when wired up in main.py.

    `port=0` binds an OS-assigned ephemeral port - used by tests so they
    never need a fixed port or elevated privileges, on any OS including
    Windows. The real device binds port 80 (see image/systemd/
    monstrapro-agent.service's AmbientCapabilities=CAP_NET_BIND_SERVICE, so
    this runs as the non-root `monstrapro` user without needing full root).
    """

    def __init__(self, scanner: WifiScanner, *, host: str = "0.0.0.0", port: int = 80) -> None:
        self._submissions: "queue.Queue[SubmittedCredentials]" = queue.Queue()
        handler = _make_handler(scanner, self._submissions)
        self._httpd = ThreadingHTTPServer((host, port), handler)
        self._thread = threading.Thread(target=self._httpd.serve_forever, daemon=True)

    @property
    def port(self) -> int:
        return self._httpd.server_address[1]

    def start(self) -> None:
        self._thread.start()

    def poll(self) -> SubmittedCredentials | None:
        try:
            return self._submissions.get_nowait()
        except queue.Empty:
            return None

    def stop(self) -> None:
        self._httpd.shutdown()
        self._httpd.server_close()
