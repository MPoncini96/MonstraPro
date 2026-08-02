"""HTML rendering for the local portfolio-editing page - stdlib-only, same
"minimal dependencies" principle as device_agent/setup_server.py. Pure
functions returning bytes: no I/O, easy to unit test without a real HTTP
server.
"""

from __future__ import annotations

import html
from typing import Any

PAGE_TITLE = "Monstra Pro Portfolio"

_STYLE = """
body { font-family: sans-serif; max-width: 480px; margin: 2rem auto; padding: 0 1rem; }
.error { color: #b00020; }
.message { color: #1f9d63; }
label { display: block; margin-top: 1rem; }
input, button { width: 100%; padding: 0.5rem; margin-top: 0.25rem; box-sizing: border-box; }
button { margin-top: 1rem; cursor: pointer; }
.bot-row { display: flex; align-items: center; gap: 0.5rem; margin-top: 0.5rem; }
.bot-row label { margin-top: 0; }
.holding-row { display: flex; align-items: center; justify-content: space-between; gap: 0.5rem; margin-top: 0.5rem; }
.holding-row form { display: inline; width: auto; margin: 0; }
.holding-row button { width: auto; padding: 0.25rem 0.75rem; margin-top: 0; }
h2 { margin-top: 2rem; }
"""


def render_login_page(*, error: str | None = None) -> bytes:
    error_html = f'<p class="error">{html.escape(error)}</p>' if error else ""
    return (
        f'<!doctype html><html><head><meta charset="utf-8">'
        f'<meta name="viewport" content="width=device-width, initial-scale=1">'
        f"<title>{PAGE_TITLE}</title><style>{_STYLE}</style></head><body>"
        f"<h1>Monstra Pro</h1>"
        f"<p>Enter the PIN shown on the device's screen.</p>"
        f"{error_html}"
        f'<form method="post" action="/login">'
        f'<label>PIN<input type="text" name="pin" inputmode="numeric" autocomplete="off" autofocus></label>'
        f'<button type="submit">Unlock</button>'
        f"</form></body></html>"
    ).encode("utf-8")


def render_portfolio_page(
    *, bots: list[dict[str, Any]], holdings: list[dict[str, Any]], message: str | None = None
) -> bytes:
    message_html = f'<p class="message">{html.escape(message)}</p>' if message else ""

    bot_rows = "".join(
        f'<div class="bot-row"><input type="checkbox" name="bot" value="{html.escape(b["slug"])}" '
        f'id="bot-{html.escape(b["slug"])}"{" checked" if b["is_active"] else ""}>'
        f'<label for="bot-{html.escape(b["slug"])}">{html.escape(b["display_name"])}</label></div>'
        for b in bots
    )

    holding_rows = (
        "".join(
            f'<div class="holding-row"><span>{html.escape(h["symbol"])} &times; {h["target_qty"]:g} shares</span>'
            f'<form method="post" action="/portfolio/holdings/remove">'
            f'<input type="hidden" name="symbol" value="{html.escape(h["symbol"])}">'
            f'<button type="submit">Remove</button></form></div>'
            for h in holdings
        )
        or "<p>No locked stocks added yet.</p>"
    )

    return (
        f'<!doctype html><html><head><meta charset="utf-8">'
        f'<meta name="viewport" content="width=device-width, initial-scale=1">'
        f"<title>{PAGE_TITLE}</title><style>{_STYLE}</style></head><body>"
        f"<h1>Your portfolio</h1>"
        f"{message_html}"
        f"<h2>Bots</h2>"
        f"<p>Toggle which strategies are active. Bots manage their own allocation - "
        f"you don't set weights directly.</p>"
        f'<form method="post" action="/portfolio/bots">{bot_rows}'
        f'<button type="submit">Save bots</button></form>'
        f"<h2>Locked stocks</h2>"
        f"<p>Held outside of any bot's control - bots will never buy or sell these. "
        f"Adding one buys up to the quantity you set; removing one only stops "
        f"protecting it, it does not sell your shares.</p>"
        f"{holding_rows}"
        f'<form method="post" action="/portfolio/holdings/add">'
        f'<label>Symbol<input type="text" name="symbol" autocomplete="off" '
        f'style="text-transform:uppercase"></label>'
        f'<label>Quantity (shares)<input type="number" name="target_qty" min="0.0001" step="any"></label>'
        f'<button type="submit">Add locked stock</button></form>'
        f'<p><a href="/logout">Log out</a></p>'
        f"</body></html>"
    ).encode("utf-8")
