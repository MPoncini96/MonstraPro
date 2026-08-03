from datetime import datetime, timedelta, timezone

import requests

from trading_worker.activation import HTTPActivationClient, LocalActivationClient


def test_not_activated_before_device_row_exists(core):
    client = LocalActivationClient(core)

    status = client.check_status()

    assert status.activated is False
    assert status.owner_ref is None
    assert status.device_serial is not None  # get_or_create() always assigns a serial


def test_activated_after_device_repository_activate(core):
    client = LocalActivationClient(core)
    core.devices.get_or_create()
    core.devices.activate(owner_ref="cust_123")

    status = client.check_status()

    assert status.activated is True
    assert status.owner_ref == "cust_123"
    assert status.device_serial is not None


def test_check_status_creates_device_row_if_missing(core):
    client = LocalActivationClient(core)

    client.check_status()

    assert core.devices.get() is not None


class _FakeResponse:
    def __init__(self, status_code: int = 200, json_data=None):
        self.status_code = status_code
        self._json_data = json_data or {}

    def raise_for_status(self) -> None:
        if self.status_code >= 400:
            raise requests.HTTPError(f"{self.status_code} error")

    def json(self):
        return self._json_data


class _FakeSession:
    """Records every call so tests can assert on exactly what
    HTTPActivationClient sent, and lets each response (or exception) be
    queued up front - matches this codebase's existing injectable-I/O
    pattern (e.g. device_agent's SimulatedNetworkManager)."""

    def __init__(self, *, register_response=None, status_responses=None):
        self._register_response = register_response
        self._status_responses = list(status_responses or [])
        self.register_calls: list[tuple[str, dict]] = []
        self.status_calls: list[tuple[str, dict]] = []

    def post(self, url, json, timeout):
        self.register_calls.append((url, json))
        if isinstance(self._register_response, Exception):
            raise self._register_response
        return self._register_response

    def get(self, url, headers, timeout):
        self.status_calls.append((url, headers))
        if not self._status_responses:
            raise AssertionError("HTTPActivationClient polled more times than the test expected")
        response = self._status_responses.pop(0)
        if isinstance(response, Exception):
            raise response
        return response


def _register_response(*, device_token="mpb_live_abc.secret", pairing_code="ABCD1234", ttl_minutes=15):
    expires_at = datetime.now(timezone.utc) + timedelta(minutes=ttl_minutes)
    return _FakeResponse(
        200,
        {
            "deviceId": "dev_123",
            "deviceToken": device_token,
            "pairingCode": pairing_code,
            "pairingCodeExpiresAt": expires_at.isoformat().replace("+00:00", "Z"),
        },
    )


def test_http_client_registers_when_no_token_stored_yet(core):
    session = _FakeSession(
        register_response=_register_response(pairing_code="ABCD1234"),
        status_responses=[_FakeResponse(200, {"activated": False, "ownerLinked": False})],
    )
    client = HTTPActivationClient(core, session=session)

    status = client.check_status()

    assert len(session.register_calls) == 1
    url, body = session.register_calls[0]
    assert url.endswith("/api/devices/register")
    assert body == {"serial": core.devices.get().serial}
    assert status.activated is False
    assert status.pairing_code == "ABCD1234"
    assert core.devices.get().has_device_token is True


def test_http_client_polls_status_with_bearer_token(core):
    session = _FakeSession(
        register_response=_register_response(device_token="mpb_live_the-token"),
        status_responses=[_FakeResponse(200, {"activated": False, "ownerLinked": False})],
    )
    client = HTTPActivationClient(core, session=session)

    client.check_status()

    assert len(session.status_calls) == 1
    url, headers = session.status_calls[0]
    assert url.endswith("/api/devices/status")
    assert headers["Authorization"] == "Bearer mpb_live_the-token"


def test_http_client_activates_locally_once_server_confirms(core):
    session = _FakeSession(
        register_response=_register_response(),
        status_responses=[_FakeResponse(200, {"activated": True, "ownerLinked": True})],
    )
    client = HTTPActivationClient(core, session=session)

    status = client.check_status()

    assert status.activated is True
    assert status.owner_ref == HTTPActivationClient.OWNER_REF
    reloaded = core.devices.get()
    assert reloaded.is_activated is True


def test_http_client_rechecks_with_server_even_once_locally_activated(core):
    """A website-side disconnect (NextJS_Monsta's
    POST /api/devices/[deviceId]/disconnect) must reach an already-running
    device, not just a freshly-restarted one - so check_status() re-verifies
    with monstra.pro on every call rather than trusting the local activated
    flag forever."""
    core.devices.get_or_create()
    core.devices.activate(owner_ref="cust_123")
    core.devices.store_registration(
        device_token="mpb_live_still-good",
        pairing_code=None,
        pairing_code_expires_at=datetime.now(timezone.utc) + timedelta(minutes=15),
    )
    session = _FakeSession(status_responses=[_FakeResponse(200, {"activated": True, "ownerLinked": True})])
    client = HTTPActivationClient(core, session=session)

    status = client.check_status()

    assert status.activated is True
    assert status.owner_ref == "cust_123"
    assert session.register_calls == []
    assert len(session.status_calls) == 1


def test_http_client_recheck_network_failure_does_not_deactivate(core):
    """A transient Wi-Fi blip must not itself kick an already-paired device
    offline - only a definitive server signal (401, or an explicit
    `activated: false`) does that. See _recheck_activated's docstring."""
    core.devices.get_or_create()
    core.devices.activate(owner_ref="cust_123")
    core.devices.store_registration(
        device_token="mpb_live_still-good",
        pairing_code=None,
        pairing_code_expires_at=datetime.now(timezone.utc) + timedelta(minutes=15),
    )
    session = _FakeSession(status_responses=[requests.ConnectionError("network down")])
    client = HTTPActivationClient(core, session=session)

    status = client.check_status()

    assert status.activated is True
    assert core.devices.get().is_activated is True


def test_http_client_recheck_401_deactivates_locally(core):
    """A revoked token (owner disconnected the device from monstra.pro) gets
    a definitive 401 from /api/devices/status - that must deactivate the
    device locally, and clear its now-dead token so the next check_status()
    call registers fresh, exactly like a never-yet-activated device."""
    core.devices.get_or_create()
    core.devices.activate(owner_ref="cust_123")
    core.devices.store_registration(
        device_token="mpb_live_revoked",
        pairing_code=None,
        pairing_code_expires_at=datetime.now(timezone.utc) + timedelta(minutes=15),
    )
    session = _FakeSession(status_responses=[_FakeResponse(401)])
    client = HTTPActivationClient(core, session=session)

    status = client.check_status()

    assert status.activated is False
    reloaded = core.devices.get()
    assert reloaded.is_activated is False
    assert reloaded.owner_ref is None
    assert reloaded.has_device_token is False


def test_http_client_recheck_explicit_activated_false_deactivates(core):
    session_device_token = "mpb_live_still-good"
    core.devices.get_or_create()
    core.devices.activate(owner_ref="cust_123")
    core.devices.store_registration(
        device_token=session_device_token,
        pairing_code=None,
        pairing_code_expires_at=datetime.now(timezone.utc) + timedelta(minutes=15),
    )
    session = _FakeSession(status_responses=[_FakeResponse(200, {"activated": False, "ownerLinked": False})])
    client = HTTPActivationClient(core, session=session)

    status = client.check_status()

    assert status.activated is False
    assert core.devices.get().is_activated is False


def test_http_client_recheck_with_no_token_deactivates_without_network_call(core):
    core.devices.get_or_create()
    core.devices.activate(owner_ref="cust_123")
    session = _FakeSession()  # any post()/get() call raises AssertionError - none queued
    client = HTTPActivationClient(core, session=session)

    status = client.check_status()

    assert status.activated is False
    assert session.status_calls == []


def test_http_client_registration_failure_does_not_raise(core):
    session = _FakeSession(register_response=requests.ConnectionError("network down"))
    client = HTTPActivationClient(core, session=session)

    status = client.check_status()

    assert status.activated is False
    assert status.pairing_code is None


def test_http_client_poll_failure_does_not_raise(core):
    session = _FakeSession(
        register_response=_register_response(pairing_code="EXIST123"),
        status_responses=[requests.ConnectionError("network down")],
    )
    client = HTTPActivationClient(core, session=session)

    status = client.check_status()

    assert status.activated is False
    assert status.pairing_code == "EXIST123"


def test_http_client_reregisters_when_the_stored_pairing_code_has_expired(core):
    core.devices.get_or_create()
    core.devices.store_registration(
        device_token="mpb_live_stale",
        pairing_code="STALE111",
        pairing_code_expires_at=datetime.now(timezone.utc) - timedelta(minutes=1),
    )
    session = _FakeSession(
        register_response=_register_response(device_token="mpb_live_fresh", pairing_code="FRESH222"),
        status_responses=[_FakeResponse(200, {"activated": False, "ownerLinked": False})],
    )
    client = HTTPActivationClient(core, session=session)

    status = client.check_status()

    assert len(session.register_calls) == 1
    assert status.pairing_code == "FRESH222"
    _, headers = session.status_calls[0]
    assert headers["Authorization"] == "Bearer mpb_live_fresh"


def test_http_client_does_not_reregister_while_pairing_code_still_valid(core):
    core.devices.get_or_create()
    core.devices.store_registration(
        device_token="mpb_live_still-good",
        pairing_code="STILLGOOD",
        pairing_code_expires_at=datetime.now(timezone.utc) + timedelta(minutes=10),
    )
    session = _FakeSession(status_responses=[_FakeResponse(200, {"activated": False, "ownerLinked": False})])
    client = HTTPActivationClient(core, session=session)

    status = client.check_status()

    assert session.register_calls == []
    assert status.pairing_code == "STILLGOOD"
