from datetime import datetime, timedelta, timezone

import requests

from trading_worker.alpaca_sync import sync_alpaca_credentials_if_missing


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
    def __init__(self, *, get_response=None):
        self._get_response = get_response
        self.calls: list[tuple[str, dict]] = []

    def get(self, url, headers, timeout):
        self.calls.append((url, headers))
        if isinstance(self._get_response, Exception):
            raise self._get_response
        return self._get_response


class _ExplodingSession:
    """Any call means the "already have local credentials" short-circuit
    failed to actually short-circuit."""

    def get(self, *args, **kwargs):
        raise AssertionError("sync_alpaca_credentials_if_missing must not touch the network")


def _register(core, *, device_token="mpb_live_token"):
    core.devices.get_or_create()
    core.devices.store_registration(
        device_token=device_token,
        pairing_code="ABCD1234",
        pairing_code_expires_at=datetime.now(timezone.utc) + timedelta(minutes=15),
    )


def test_returns_true_without_any_network_call_when_credentials_already_exist(core):
    core.credentials.save(mode="paper", api_key="k", api_secret="s", base_url="https://paper-api.alpaca.markets")

    result = sync_alpaca_credentials_if_missing(core, session=_ExplodingSession())

    assert result is True


def test_returns_false_when_device_has_never_registered(core):
    core.devices.get_or_create()  # no store_registration() - no device_token yet

    result = sync_alpaca_credentials_if_missing(core, session=_ExplodingSession())

    assert result is False


def test_fetches_and_stores_credentials_on_success(core):
    _register(core, device_token="mpb_live_the-token")
    session = _FakeSession(
        get_response=_FakeResponse(
            200,
            {
                "connected": True,
                "mode": "live",
                "apiKey": "AKLIVE123",
                "secretKey": "SECRETLIVE",
                "baseUrl": "https://api.alpaca.markets",
            },
        )
    )

    result = sync_alpaca_credentials_if_missing(core, session=session)

    assert result is True
    assert len(session.calls) == 1
    url, headers = session.calls[0]
    assert url.endswith("/api/devices/alpaca-credentials")
    assert headers["Authorization"] == "Bearer mpb_live_the-token"

    stored = core.credentials.get("live")
    assert stored["api_key"] == "AKLIVE123"
    assert stored["api_secret"] == "SECRETLIVE"
    assert stored["base_url"] == "https://api.alpaca.markets"


def test_returns_false_when_server_reports_not_connected_yet(core):
    _register(core)
    session = _FakeSession(get_response=_FakeResponse(200, {"connected": False}))

    result = sync_alpaca_credentials_if_missing(core, session=session)

    assert result is False
    assert core.credentials.get("paper") is None
    assert core.credentials.get("live") is None


def test_returns_false_on_network_failure_without_raising(core):
    _register(core)
    session = _FakeSession(get_response=requests.ConnectionError("network down"))

    result = sync_alpaca_credentials_if_missing(core, session=session)

    assert result is False
