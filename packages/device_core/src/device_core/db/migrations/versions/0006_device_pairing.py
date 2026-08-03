"""monstra.pro device pairing: device.pairing_code,
device.pairing_code_expires_at, device.device_token_encrypted

Revision ID: 0006
Revises: 0005
Create Date: 2026-08-02

Hand-written (no autogenerate), mirroring device_core/db/models.py
column-for-column, same convention as 0001-0005.
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0006"
down_revision: Union[str, None] = "0005"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("device", sa.Column("pairing_code", sa.String(length=16), nullable=True))
    op.add_column(
        "device", sa.Column("pairing_code_expires_at", sa.DateTime(timezone=True), nullable=True)
    )
    op.add_column("device", sa.Column("device_token_encrypted", sa.Text(), nullable=True))


def downgrade() -> None:
    op.drop_column("device", "device_token_encrypted")
    op.drop_column("device", "pairing_code_expires_at")
    op.drop_column("device", "pairing_code")
