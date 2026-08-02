"""updater schema: software_release

Revision ID: 0003
Revises: 0002
Create Date: 2026-08-01

Hand-written (no autogenerate), mirroring device_core/db/models.py
column-for-column, same convention as 0001/0002.
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0003"
down_revision: Union[str, None] = "0002"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "software_release",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("version", sa.String(length=32), nullable=False, index=True),
        sa.Column("status", sa.String(length=16), nullable=False, index=True),
        sa.Column("manifest_json", sa.JSON(), nullable=True),
        sa.Column("staged_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("activated_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("rolled_back_at", sa.DateTime(timezone=True), nullable=True),
        sa.UniqueConstraint("version", name="uq_software_release_version"),
    )


def downgrade() -> None:
    op.drop_table("software_release")
