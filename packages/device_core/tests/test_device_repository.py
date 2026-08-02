from device_core.db.session import Database
from device_core.repositories.device import DeviceRepository


def test_get_or_create_is_idempotent(config):
    db = Database(config)
    repo = DeviceRepository(db)

    first = repo.get_or_create()
    second = repo.get_or_create()

    assert first.id == second.id
    assert first.serial == second.serial
    assert first.is_activated is False


def test_activate_sets_activation_fields(config):
    db = Database(config)
    repo = DeviceRepository(db)

    device = repo.get_or_create()
    assert device.is_activated is False

    activated = repo.activate(owner_ref="cust_123")

    assert activated.id == device.id
    assert activated.is_activated is True
    assert activated.owner_ref == "cust_123"
    assert activated.disclosures_accepted_at is not None

    reloaded = repo.get()
    assert reloaded.is_activated is True
    assert reloaded.owner_ref == "cust_123"


def test_record_software_version(config):
    db = Database(config)
    repo = DeviceRepository(db)
    repo.get_or_create()

    updated = repo.record_software_version("0.1.0")

    assert updated.software_version == "0.1.0"


def test_get_or_create_local_pin_is_six_digits(config):
    repo = DeviceRepository(Database(config))

    pin = repo.get_or_create_local_pin()

    assert len(pin) == 6
    assert pin.isdigit()


def test_get_or_create_local_pin_is_stable_across_calls(config):
    repo = DeviceRepository(Database(config))

    first = repo.get_or_create_local_pin()
    second = repo.get_or_create_local_pin()

    assert first == second


def test_get_or_create_local_pin_creates_device_row_if_missing(config):
    repo = DeviceRepository(Database(config))

    repo.get_or_create_local_pin()

    assert repo.get() is not None


def test_local_pin_is_visible_on_the_device_dataclass(config):
    repo = DeviceRepository(Database(config))

    pin = repo.get_or_create_local_pin()
    device = repo.get()

    assert device.local_pin == pin
