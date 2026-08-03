from datetime import datetime, timedelta, timezone

import requests

from trading_worker.run_request import ack_run_request, check_run_requested


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
    def __init__(self, *, get_response=None, post_response=None):
        self._get_response = get_response
        self._post_response = post_response if post_response is not None else _FakeResponse(200)
        self.get_calls: list[tuple[str, dict]] = []
        self.post_calls: list[tuple[str, dict]] = []

    def get(self, url, headers, timeout):
        self.get_calls.append((url, headers))
        if isinstance(self._get_response, Exception):
            raise self._get_response
        return self._get_response

    def post(self, url, headers, timeout):
        self.post_calls.append((url, headers))
        if isinstance(self._post_response, Exception):
            raise self._post_response
        return self._post_response


class _ExplodingSession:
    def get(self, *args, **kwargs):
        raise AssertionError("must not touch the network without a device token")

    def post(self, *args, **kwargs):
        raise AssertionError("must not touch the network without a device token")


def _register(core, *, device_token="mpb_live_token"):
    core.devices.get_or_create()
    core.devices.store_registration(
        device_token=device_token,
        pairing_code="ABCD1234",
        pairing_code_expires_at=datetime.now(timezone.utc) + timedelta(minutes=15),
    )


def test_check_run_requested_returns_false_when_device_has_never_registered(core):
    core.devices.get_or_create()

    result = check_run_requested(core, session=_ExplodingSession())

    assert result is False


def test_check_run_requested_true_when_server_reports_requested(core):
    _register(core, device_token="mpb_live_the-token")
    session = _FakeSession(get_response=_FakeResponse(200, {"requested": True, "requestedAt": "2026-08-03T14:30:00.000Z"}))

    result = check_run_requested(core, session=session)

    assert result is True
    url, headers = session.get_calls[0]
    assert url.endswith("/api/devices/run-request")
    assert headers["Authorization"] == "Bearer mpb_live_the-token"


def test_check_run_requested_false_when_server_reports_not_requested(core):
    _register(core)
    session = _FakeSession(get_response=_FakeResponse(200, {"requested": False, "requestedAt": None}))

    result = check_run_requested(core, session=session)

    assert result is False


def test_check_run_requested_false_on_network_failure_without_raising(core):
    _register(core)
    session = _FakeSession(get_response=requests.ConnectionError("network down"))

    result = check_run_requested(core, session=session)

    assert result is False


def test_ack_run_request_sends_authenticated_post(core):
    _register(core, device_token="mpb_live_the-token")
    session = _FakeSession()

    ack_run_request(core, session=session)

    assert len(session.post_calls) == 1
    url, headers = session.post_calls[0]
    assert url.endswith("/api/devices/run-request/ack")
    assert headers["Authorization"] == "Bearer mpb_live_the-token"


def test_ack_run_request_without_token_does_not_touch_network(core):
    core.devices.get_or_create()

    ack_run_request(core, session=_ExplodingSession())


def test_ack_run_request_failure_does_not_raise(core):
    _register(core)
    session = _FakeSession(post_response=requests.ConnectionError("network down"))

    ack_run_request(core, session=session)
