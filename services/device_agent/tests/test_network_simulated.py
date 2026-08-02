from device_agent.network import SimulatedNetworkManager, WifiNetwork


def test_initially_disconnected_has_no_usable_connection():
    network = SimulatedNetworkManager()

    assert network.has_usable_connection() is False


def test_initially_connected_flag_reports_usable_connection():
    network = SimulatedNetworkManager(initially_connected=True)

    assert network.has_usable_connection() is True


def test_start_stop_ap_records_state_and_calls():
    network = SimulatedNetworkManager()

    network.start("MonstraPro-AB12")
    assert network.ap_active is True
    assert network.ap_ssid == "MonstraPro-AB12"

    network.stop()
    assert network.ap_active is False
    assert network.calls == ["start:MonstraPro-AB12", "stop"]


def test_scan_returns_configured_networks():
    networks = [WifiNetwork("HomeWifi", 80, True), WifiNetwork("OpenCafe", 40, False)]
    network = SimulatedNetworkManager(available_networks=networks)

    assert network.scan() == networks


def test_connect_and_save_success_marks_connection_usable():
    network = SimulatedNetworkManager()

    assert network.connect_and_save("HomeWifi", "hunter2") is True
    assert network.joined_ssid == "HomeWifi"
    assert network.saved_connections == ["HomeWifi"]
    assert network.has_usable_connection() is True


def test_connect_and_save_failure_for_configured_fail_ssid():
    network = SimulatedNetworkManager(fail_ssids=frozenset({"WrongPassword"}))

    assert network.connect_and_save("WrongPassword", "nope") is False
    assert network.joined_ssid is None
    assert network.has_usable_connection() is False
