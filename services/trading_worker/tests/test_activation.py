from trading_worker.activation import LocalActivationClient


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
