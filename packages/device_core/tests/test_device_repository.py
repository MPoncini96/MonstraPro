from datetime import datetime, timedelta, timezone
from pathlib import Path

from device_core.db.session import Database
from device_core.repositories.device import DeviceRepository
from device_core.vault import Vault


def _repo(config):
    db = Database(config)
    vault = Vault.load_or_create(config.encryption_key_path)
    return db, DeviceRepository(db, vault)


def test_get_or_create_is_idempotent(config):
    db, repo = _repo(config)

    first = repo.get_or_create()
    second = repo.get_or_create()

    assert first.id == second.id
    assert first.serial == second.serial
    assert first.is_activated is False


def test_activate_sets_activation_fields(config):
    db, repo = _repo(config)

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


def test_activate_burns_any_pending_pairing_code(config):
    """Regression guard: a stale plaintext pairing code must not linger once
    the device is actually paired - mirrors monstra.pro's own
    /api/devices/pair, which nulls the code out server-side on use."""
    _, repo = _repo(config)
    repo.get_or_create()
    repo.store_registration(
        device_token="mpb_live_abc.secret",
        pairing_code="ABCD1234",
        pairing_code_expires_at=datetime.now(timezone.utc) + timedelta(minutes=15),
    )

    activated = repo.activate(owner_ref="cust_123")

    assert activated.pairing_code is None
    assert activated.pairing_code_expires_at is None


def test_record_software_version(config):
    db, repo = _repo(config)
    repo.get_or_create()

    updated = repo.record_software_version("0.1.0")

    assert updated.software_version == "0.1.0"


def test_get_or_create_local_pin_is_six_digits(config):
    _, repo = _repo(config)

    pin = repo.get_or_create_local_pin()

    assert len(pin) == 6
    assert pin.isdigit()


def test_get_or_create_local_pin_is_stable_across_calls(config):
    _, repo = _repo(config)

    first = repo.get_or_create_local_pin()
    second = repo.get_or_create_local_pin()

    assert first == second


def test_get_or_create_local_pin_creates_device_row_if_missing(config):
    _, repo = _repo(config)

    repo.get_or_create_local_pin()

    assert repo.get() is not None


def test_local_pin_is_visible_on_the_device_dataclass(config):
    _, repo = _repo(config)

    pin = repo.get_or_create_local_pin()
    device = repo.get()

    assert device.local_pin == pin


def test_store_registration_persists_pairing_code_in_plaintext(config):
    """pairing_code must be readable back as plaintext (unlike the device
    token) - display needs to render it on the LCD verbatim."""
    _, repo = _repo(config)
    repo.get_or_create()
    expires_at = datetime.now(timezone.utc) + timedelta(minutes=15)

    device = repo.store_registration(
        device_token="mpb_live_abc.secret", pairing_code="ABCD1234", pairing_code_expires_at=expires_at
    )

    assert device.pairing_code == "ABCD1234"
    assert device.pairing_code_expires_at == expires_at
    assert device.has_device_token is True


def test_device_token_is_never_stored_as_plaintext(config):
    db, repo = _repo(config)
    repo.get_or_create()

    repo.store_registration(
        device_token="mpb_live_super-secret-token",
        pairing_code="ABCD1234",
        pairing_code_expires_at=datetime.now(timezone.utc) + timedelta(minutes=15),
    )

    db_path = config.sqlite_url.removeprefix("sqlite:///")
    raw_bytes = Path(db_path).read_bytes()
    assert b"mpb_live_super-secret-token" not in raw_bytes


def test_get_device_token_round_trips_the_raw_token(config):
    _, repo = _repo(config)
    repo.get_or_create()
    repo.store_registration(
        device_token="mpb_live_abc.secret",
        pairing_code="ABCD1234",
        pairing_code_expires_at=datetime.now(timezone.utc) + timedelta(minutes=15),
    )

    assert repo.get_device_token() == "mpb_live_abc.secret"


def test_get_device_token_is_none_before_registration(config):
    _, repo = _repo(config)
    repo.get_or_create()

    assert repo.get_device_token() is None


def test_store_registration_overwrites_a_previous_registration(config):
    """Re-registering (e.g. because the first pairing code expired unused)
    must replace the old token/code, not accumulate alongside it."""
    _, repo = _repo(config)
    repo.get_or_create()
    repo.store_registration(
        device_token="mpb_live_first",
        pairing_code="FIRST111",
        pairing_code_expires_at=datetime.now(timezone.utc) + timedelta(minutes=15),
    )

    repo.store_registration(
        device_token="mpb_live_second",
        pairing_code="SECOND22",
        pairing_code_expires_at=datetime.now(timezone.utc) + timedelta(minutes=15),
    )

    assert repo.get_device_token() == "mpb_live_second"
    assert repo.get().pairing_code == "SECOND22"


def test_pairing_code_expired_is_true_when_no_code_has_ever_been_issued(config):
    _, repo = _repo(config)
    device = repo.get_or_create()

    assert device.pairing_code_expired is True


def test_pairing_code_expired_reflects_the_stored_expiry(config):
    _, repo = _repo(config)
    repo.get_or_create()
    repo.store_registration(
        device_token="mpb_live_abc.secret",
        pairing_code="ABCD1234",
        pairing_code_expires_at=datetime.now(timezone.utc) - timedelta(minutes=1),
    )

    assert repo.get().pairing_code_expired is True
