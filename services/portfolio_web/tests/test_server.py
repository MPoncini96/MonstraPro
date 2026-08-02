"""PortfolioServer runs on a real (loopback-only) TCP socket, bound to an
OS-assigned ephemeral port (port=0) - plain Python networking, not
NetworkManager/access-point/system config, so it's safe to exercise on any
OS including Windows, per this project's rules.
"""

import http.cookiejar
import urllib.parse
import urllib.request
from urllib.error import HTTPError

from portfolio_web.auth import SessionStore
from portfolio_web.server import PortfolioServer


def _opener():
    jar = http.cookiejar.CookieJar()
    return urllib.request.build_opener(urllib.request.HTTPCookieProcessor(jar))


def _start_server(core):
    server = PortfolioServer(core, SessionStore(), host="127.0.0.1", port=0)
    server.start()
    return server


def _base_url(server):
    return f"http://127.0.0.1:{server.port}"


def _post(opener, url, data):
    # doseq=True so a list value (e.g. {"bot": ["force", "draco"]}) encodes
    # as repeated bot=force&bot=draco fields, matching what a real <form>
    # with multiple checked checkboxes of the same name submits - without
    # it, urlencode would stringify the whole list into one bogus value.
    encoded = urllib.parse.urlencode(data, doseq=True).encode()
    request = urllib.request.Request(url, data=encoded, method="POST")
    return opener.open(request)


def _login(opener, base_url, pin):
    return _post(opener, f"{base_url}/login", {"pin": pin})


def test_root_shows_login_page_when_not_authenticated(core):
    server = _start_server(core)
    try:
        with urllib.request.urlopen(f"{_base_url(server)}/") as response:
            body = response.read()
        assert b"PIN" in body
    finally:
        server.stop()


def test_portfolio_redirects_to_login_when_not_authenticated(core):
    server = _start_server(core)
    try:
        with urllib.request.urlopen(f"{_base_url(server)}/portfolio") as response:
            assert response.geturl() == f"{_base_url(server)}/"
    finally:
        server.stop()


def test_login_with_wrong_pin_is_rejected(core):
    server = _start_server(core)
    try:
        opener = _opener()
        try:
            _login(opener, _base_url(server), "000000")
            raise AssertionError("expected HTTPError")
        except HTTPError as exc:
            assert exc.code == 401
    finally:
        server.stop()


def test_login_with_correct_pin_grants_access_to_portfolio(core):
    pin = core.devices.get_or_create_local_pin()
    server = _start_server(core)
    try:
        opener = _opener()
        response = _login(opener, _base_url(server), pin)
        assert response.geturl() == f"{_base_url(server)}/portfolio"

        with opener.open(f"{_base_url(server)}/portfolio") as portfolio_response:
            assert portfolio_response.geturl() == f"{_base_url(server)}/portfolio"
    finally:
        server.stop()


def test_saving_bots_updates_strategy_config(core):
    pin = core.devices.get_or_create_local_pin()
    server = _start_server(core)
    try:
        opener = _opener()
        _login(opener, _base_url(server), pin)

        _post(opener, f"{_base_url(server)}/portfolio/bots", {"bot": ["force", "draco"]})

        active = {row["bot_slug"] for row in core.strategies.get_active()}
        assert active == {"force", "draco"}
        force_row = core.strategies.get("force")
        assert force_row["source"] == "local"
    finally:
        server.stop()


def test_unselecting_a_bot_deactivates_it(core):
    core.strategies.upsert(bot_slug="force", display_name="Force", is_active=True)
    pin = core.devices.get_or_create_local_pin()
    server = _start_server(core)
    try:
        opener = _opener()
        _login(opener, _base_url(server), pin)

        _post(opener, f"{_base_url(server)}/portfolio/bots", {"bot": ["aptet"]})

        assert core.strategies.get("force")["is_active"] is False
    finally:
        server.stop()


def test_adding_a_locked_holding(core):
    pin = core.devices.get_or_create_local_pin()
    server = _start_server(core)
    try:
        opener = _opener()
        _login(opener, _base_url(server), pin)

        _post(opener, f"{_base_url(server)}/portfolio/holdings/add", {"symbol": "aapl", "target_qty": "10"})

        [holding] = core.manual_holdings.list_all()
        assert holding["symbol"] == "AAPL"  # normalized to uppercase
        assert holding["target_qty"] == 10.0
    finally:
        server.stop()


def test_adding_a_holding_with_invalid_quantity_does_not_persist(core):
    pin = core.devices.get_or_create_local_pin()
    server = _start_server(core)
    try:
        opener = _opener()
        _login(opener, _base_url(server), pin)

        try:
            _post(opener, f"{_base_url(server)}/portfolio/holdings/add", {"symbol": "AAPL", "target_qty": "-5"})
            raise AssertionError("expected HTTPError")
        except HTTPError as exc:
            assert exc.code == 400

        assert core.manual_holdings.list_all() == []
    finally:
        server.stop()


def test_removing_a_locked_holding(core):
    core.manual_holdings.add(symbol="AAPL", target_qty=10.0)
    pin = core.devices.get_or_create_local_pin()
    server = _start_server(core)
    try:
        opener = _opener()
        _login(opener, _base_url(server), pin)

        _post(opener, f"{_base_url(server)}/portfolio/holdings/remove", {"symbol": "AAPL"})

        assert core.manual_holdings.list_all() == []
    finally:
        server.stop()


def test_unauthenticated_post_does_not_change_anything(core):
    core.strategies.upsert(bot_slug="force", display_name="Force", is_active=True)
    server = _start_server(core)
    try:
        opener = _opener()  # fresh opener, never logged in
        _post(opener, f"{_base_url(server)}/portfolio/bots", {"bot": []})

        # If this had been applied, force would now be inactive.
        assert core.strategies.get("force")["is_active"] is True
    finally:
        server.stop()


def test_logout_revokes_the_session(core):
    pin = core.devices.get_or_create_local_pin()
    server = _start_server(core)
    try:
        opener = _opener()
        _login(opener, _base_url(server), pin)
        opener.open(f"{_base_url(server)}/logout").read()

        with opener.open(f"{_base_url(server)}/portfolio") as response:
            assert response.geturl() == f"{_base_url(server)}/"
    finally:
        server.stop()
