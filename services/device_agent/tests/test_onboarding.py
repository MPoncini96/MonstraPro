from device_agent.network import SimulatedNetworkManager
from device_agent.onboarding import SETUP_URL, SubmittedCredentials, run_onboarding


class QueuedSubmissions:
    """Fake SetupSubmissionSource: returns queued items one per poll(),
    then None once drained - mirrors how setup_server.SetupServer's queue
    behaves without needing a real HTTP server in these tests."""

    def __init__(self, items):
        self._items = list(items)

    def poll(self):
        if self._items:
            return self._items.pop(0)
        return None


def _event_types(core):
    return [e["type"] for e in core.events.list_unconsumed()]


def test_already_connected_skips_onboarding_entirely(core):
    network = SimulatedNetworkManager(initially_connected=True)

    result = run_onboarding(
        core,
        connectivity=network,
        access_point=network,
        connector=network,
        submissions=QueuedSubmissions([]),
        device_serial="MPB-AAAAAAAAAAAA",
    )

    assert result == "already_connected"
    assert network.ap_active is False
    assert "wifi_onboarding_started" not in _event_types(core)


def test_starts_ap_and_publishes_onboarding_started_event(core):
    network = SimulatedNetworkManager()
    sleeps = []

    result = run_onboarding(
        core,
        connectivity=network,
        access_point=network,
        connector=network,
        submissions=QueuedSubmissions([]),
        device_serial="MPB-AAAAAAAAAAAA",
        sleep=sleeps.append,
        max_polls=2,
    )

    assert result == "gave_up"
    assert network.ap_active is False  # stopped in the `finally` even on give-up
    onboarding_events = [e for e in core.events.list_unconsumed() if e["type"] == "wifi_onboarding_started"]
    assert len(onboarding_events) == 1
    assert onboarding_events[0]["payload_json"]["setup_url"] == SETUP_URL
    assert onboarding_events[0]["payload_json"]["ap_ssid"].startswith("MonstraPro-")
    assert sleeps == [2.0]


def test_successful_submission_joins_and_stops_ap(core):
    network = SimulatedNetworkManager()
    submissions = QueuedSubmissions([SubmittedCredentials(ssid="HomeWifi", password="hunter2")])

    result = run_onboarding(
        core,
        connectivity=network,
        access_point=network,
        connector=network,
        submissions=submissions,
        device_serial="MPB-AAAAAAAAAAAA",
        sleep=lambda s: None,
    )

    assert result == "connected"
    assert network.joined_ssid == "HomeWifi"
    assert network.ap_active is False
    assert "wifi_connected" in _event_types(core)


def test_failed_join_stays_in_ap_mode_then_succeeds_on_retry(core):
    network = SimulatedNetworkManager(fail_ssids=frozenset({"WrongPassword"}))
    submissions = QueuedSubmissions(
        [
            SubmittedCredentials(ssid="WrongPassword", password="nope"),
            SubmittedCredentials(ssid="HomeWifi", password="hunter2"),
        ]
    )

    result = run_onboarding(
        core,
        connectivity=network,
        access_point=network,
        connector=network,
        submissions=submissions,
        device_serial="MPB-AAAAAAAAAAAA",
        sleep=lambda s: None,
    )

    assert result == "connected"
    assert network.joined_ssid == "HomeWifi"
    assert _event_types(core).count("wifi_connected") == 1


def test_gives_up_after_max_polls_without_submission(core):
    network = SimulatedNetworkManager()
    sleeps = []

    result = run_onboarding(
        core,
        connectivity=network,
        access_point=network,
        connector=network,
        submissions=QueuedSubmissions([]),
        device_serial="MPB-AAAAAAAAAAAA",
        sleep=sleeps.append,
        max_polls=3,
        poll_interval_seconds=1.5,
    )

    assert result == "gave_up"
    assert sleeps == [1.5, 1.5]


def test_ap_ssid_is_derived_from_device_serial_not_the_raw_serial(core):
    network = SimulatedNetworkManager()

    run_onboarding(
        core,
        connectivity=network,
        access_point=network,
        connector=network,
        submissions=QueuedSubmissions([]),
        device_serial="MPB-SECRETSERIAL",
        sleep=lambda s: None,
        max_polls=1,
    )

    assert network.ap_ssid is not None
    assert "SECRETSERIAL" not in network.ap_ssid
