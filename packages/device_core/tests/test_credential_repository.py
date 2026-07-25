from pathlib import Path

import pytest

from device_core.db.session import Database
from device_core.repositories.credentials import CredentialRepository
from device_core.vault import Vault


def _repo(config):
    db = Database(config)
    vault = Vault.load_or_create(config.encryption_key_path)
    return db, CredentialRepository(db, vault)


def test_credentials_are_stored_only_as_ciphertext(config):
    db, repo = _repo(config)

    repo.save(
        mode="paper",
        api_key="AKPUBLIC123",
        api_secret="SUPERSECRET456",
        base_url="https://paper-api.alpaca.markets",
    )

    creds = repo.get("paper")
    assert creds["api_key"] == "AKPUBLIC123"
    assert creds["api_secret"] == "SUPERSECRET456"

    db_path = config.sqlite_url.removeprefix("sqlite:///")
    raw_bytes = Path(db_path).read_bytes()
    assert b"SUPERSECRET456" not in raw_bytes
    assert b"AKPUBLIC123" not in raw_bytes


def test_paper_and_live_credentials_coexist(config):
    db, repo = _repo(config)

    repo.save(mode="paper", api_key="PAPER_KEY", api_secret="PAPER_SECRET", base_url="https://paper-api.alpaca.markets")
    repo.save(mode="live", api_key="LIVE_KEY", api_secret="LIVE_SECRET", base_url="https://api.alpaca.markets")

    paper = repo.get("paper")
    live = repo.get("live")

    assert paper["api_key"] == "PAPER_KEY"
    assert live["api_key"] == "LIVE_KEY"
    assert paper["base_url"] != live["base_url"]


def test_save_overwrites_same_mode_without_duplicating(config):
    db, repo = _repo(config)

    repo.save(mode="paper", api_key="OLD_KEY", api_secret="OLD_SECRET", base_url="https://paper-api.alpaca.markets")
    repo.save(mode="paper", api_key="NEW_KEY", api_secret="NEW_SECRET", base_url="https://paper-api.alpaca.markets")

    creds = repo.get("paper")
    assert creds["api_key"] == "NEW_KEY"

    with db.session() as session:
        from device_core.db.models import AlpacaCredentials

        count = session.query(AlpacaCredentials).filter_by(mode="paper").count()
        assert count == 1


def test_get_missing_mode_returns_none(config):
    _, repo = _repo(config)
    assert repo.get("live") is None


def test_invalid_mode_rejected(config):
    _, repo = _repo(config)
    with pytest.raises(ValueError):
        repo.save(mode="bogus", api_key="x", api_secret="y", base_url="https://example.com")
