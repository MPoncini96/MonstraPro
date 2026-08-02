"""SoftwareReleaseRepository: lifecycle bookkeeping for updater's staged
releases. Tracking is separate from the actual on-disk release directories
(services/updater/src/updater/release_store.py owns those) - this is just
the "what happened, when, in what order" ledger.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from device_core.db.models import SoftwareRelease
from device_core.db.session import Database


def _row_to_dict(row: SoftwareRelease) -> dict[str, Any]:
    return {column.name: getattr(row, column.name) for column in row.__table__.columns}


class SoftwareReleaseRepository:
    def __init__(self, db: Database) -> None:
        self._db = db

    def stage(self, version: str, *, manifest: dict[str, Any] | None = None) -> dict[str, Any]:
        """Idempotent per version: re-staging an already-known version just
        returns its existing row rather than erroring."""
        with self._db.session() as session:
            row = session.query(SoftwareRelease).filter_by(version=version).first()
            if row is None:
                row = SoftwareRelease(version=version, status="staged", manifest_json=manifest or {})
                session.add(row)
                session.flush()
            return _row_to_dict(row)

    def activate(self, version: str) -> dict[str, Any]:
        """Marks `version` active, demoting whatever was previously active
        (if anything) to "superseded"."""
        with self._db.session() as session:
            previous_active = session.query(SoftwareRelease).filter_by(status="active").first()
            if previous_active is not None:
                previous_active.status = "superseded"

            row = session.query(SoftwareRelease).filter_by(version=version).first()
            if row is None:
                raise ValueError(f"No staged release for version {version!r}; call stage() first")
            row.status = "active"
            row.activated_at = datetime.now(timezone.utc)
            session.flush()
            return _row_to_dict(row)

    def rollback_to(self, version: str) -> dict[str, Any]:
        """Marks whatever's currently active as "rolled_back" and
        reactivates `version` (which must already have an "active" or
        "superseded" row - i.e. a version that previously ran)."""
        with self._db.session() as session:
            current_active = session.query(SoftwareRelease).filter_by(status="active").first()
            if current_active is not None:
                current_active.status = "rolled_back"
                current_active.rolled_back_at = datetime.now(timezone.utc)

            row = session.query(SoftwareRelease).filter_by(version=version).first()
            if row is None:
                raise ValueError(f"No known release for version {version!r}")
            row.status = "active"
            row.activated_at = datetime.now(timezone.utc)
            session.flush()
            return _row_to_dict(row)

    def get_active(self) -> dict[str, Any] | None:
        with self._db.session() as session:
            row = session.query(SoftwareRelease).filter_by(status="active").first()
            return _row_to_dict(row) if row is not None else None

    def get(self, version: str) -> dict[str, Any] | None:
        with self._db.session() as session:
            row = session.query(SoftwareRelease).filter_by(version=version).first()
            return _row_to_dict(row) if row is not None else None

    def history(self, *, limit: int = 20) -> list[dict[str, Any]]:
        with self._db.session() as session:
            rows = session.query(SoftwareRelease).order_by(SoftwareRelease.id.desc()).limit(limit).all()
            return [_row_to_dict(row) for row in rows]
