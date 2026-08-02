import pytest

from device_core.db.session import Database
from device_core.repositories.software_release import SoftwareReleaseRepository


def test_stage_creates_a_staged_row(config):
    db = Database(config)
    repo = SoftwareReleaseRepository(db)

    row = repo.stage("1.1.0", manifest={"notes": "bugfix"})

    assert row["status"] == "staged"
    assert row["manifest_json"] == {"notes": "bugfix"}
    assert repo.get_active() is None


def test_stage_is_idempotent_per_version(config):
    db = Database(config)
    repo = SoftwareReleaseRepository(db)

    first = repo.stage("1.1.0")
    second = repo.stage("1.1.0")

    assert first["id"] == second["id"]
    assert len(repo.history()) == 1


def test_activate_requires_staging_first(config):
    db = Database(config)
    repo = SoftwareReleaseRepository(db)

    with pytest.raises(ValueError):
        repo.activate("1.1.0")


def test_activate_promotes_staged_release_and_demotes_previous_active(config):
    db = Database(config)
    repo = SoftwareReleaseRepository(db)

    repo.stage("1.0.0")
    repo.activate("1.0.0")
    repo.stage("1.1.0")
    repo.activate("1.1.0")

    assert repo.get_active()["version"] == "1.1.0"
    assert repo.get("1.0.0")["status"] == "superseded"


def test_rollback_to_reactivates_previous_version(config):
    db = Database(config)
    repo = SoftwareReleaseRepository(db)

    repo.stage("1.0.0")
    repo.activate("1.0.0")
    repo.stage("1.1.0")
    repo.activate("1.1.0")

    repo.rollback_to("1.0.0")

    assert repo.get_active()["version"] == "1.0.0"
    assert repo.get("1.1.0")["status"] == "rolled_back"
    assert repo.get("1.1.0")["rolled_back_at"] is not None


def test_rollback_to_unknown_version_raises(config):
    db = Database(config)
    repo = SoftwareReleaseRepository(db)

    with pytest.raises(ValueError):
        repo.rollback_to("9.9.9")


def test_history_returns_newest_first(config):
    db = Database(config)
    repo = SoftwareReleaseRepository(db)

    repo.stage("1.0.0")
    repo.stage("1.1.0")
    repo.stage("1.2.0")

    versions = [row["version"] for row in repo.history()]
    assert versions == ["1.2.0", "1.1.0", "1.0.0"]
