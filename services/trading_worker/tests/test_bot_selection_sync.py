from datetime import datetime, timedelta, timezone

import requests

from trading_worker.bot_selection_sync import sync_bot_selections


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
    def get(self, *args, **kwargs):
        raise AssertionError("must not touch the network without a device token")


def _register(core, *, device_token="mpb_live_token"):
    core.devices.get_or_create()
    core.devices.store_registration(
        device_token=device_token,
        pairing_code="ABCD1234",
        pairing_code_expires_at=datetime.now(timezone.utc) + timedelta(minutes=15),
    )


def test_returns_false_when_device_has_never_registered(core):
    core.devices.get_or_create()

    result = sync_bot_selections(core, session=_ExplodingSession())

    assert result is False


def test_creates_new_local_rows_for_each_selected_bot(core):
    _register(core, device_token="mpb_live_the-token")
    session = _FakeSession(
        get_response=_FakeResponse(
            200,
            {
                "bots": [
                    {"botSlug": "vectura_draco", "botType": "draco", "params": {"top_n": 5}},
                    {"botSlug": "quantus_aptet", "botType": "aptet", "params": {}},
                ],
                "alpaca": {"connected": True, "mode": "live"},
            },
        )
    )

    result = sync_bot_selections(core, session=session)

    assert result is True
    url, headers = session.calls[0]
    assert url.endswith("/api/devices/strategy-config")
    assert headers["Authorization"] == "Bearer mpb_live_the-token"

    active_slugs = {row["bot_slug"] for row in core.strategies.get_active()}
    assert active_slugs == {"vectura_draco", "quantus_aptet"}
    draco_row = core.strategies.get("vectura_draco")
    assert draco_row["bot_type"] == "draco"
    assert draco_row["params_json"] == {"top_n": 5}
    assert draco_row["source"] == "monstra.pro"


def test_deactivates_a_previously_synced_bot_no_longer_selected(core):
    _register(core)
    core.strategies.upsert(bot_slug="vectura_draco", bot_type="draco", is_active=True, source="monstra.pro")
    session = _FakeSession(get_response=_FakeResponse(200, {"bots": []}))

    sync_bot_selections(core, session=session)

    row = core.strategies.get("vectura_draco")
    assert row["is_active"] is False
    assert row["source"] == "monstra.pro"  # still tagged, just turned off


def test_updates_params_for_an_already_synced_bot(core):
    _register(core)
    core.strategies.upsert(
        bot_slug="vectura_draco", bot_type="draco", params={"top_n": 3}, is_active=True, source="monstra.pro"
    )
    session = _FakeSession(
        get_response=_FakeResponse(
            200, {"bots": [{"botSlug": "vectura_draco", "botType": "draco", "params": {"top_n": 7}}]}
        )
    )

    sync_bot_selections(core, session=session)

    assert core.strategies.get("vectura_draco")["params_json"] == {"top_n": 7}


def test_never_overwrites_a_locally_configured_bot_with_the_same_slug(core):
    """A local/test-seeded bot (source="local") sharing a slug with a
    website selection must survive untouched - mirrors updater/
    strategy_sync.py's identical rule on the software-release side."""
    _register(core)
    core.strategies.upsert(bot_slug="force", params={"custom": True}, is_active=True, source="local")
    session = _FakeSession(
        get_response=_FakeResponse(200, {"bots": [{"botSlug": "force", "botType": "force", "params": {}}]})
    )

    sync_bot_selections(core, session=session)

    row = core.strategies.get("force")
    assert row["source"] == "local"
    assert row["params_json"] == {"custom": True}


def test_returns_false_on_network_failure_without_raising(core):
    _register(core)
    session = _FakeSession(get_response=requests.ConnectionError("network down"))

    result = sync_bot_selections(core, session=session)

    assert result is False


def test_ignores_bot_entries_missing_slug_or_type(core):
    _register(core)
    session = _FakeSession(
        get_response=_FakeResponse(
            200,
            {
                "bots": [
                    {"botSlug": "vectura_draco", "botType": None, "params": {}},
                    {"botSlug": None, "botType": "aptet", "params": {}},
                ]
            },
        )
    )

    result = sync_bot_selections(core, session=session)

    assert result is True
    assert core.strategies.get_active() == []
