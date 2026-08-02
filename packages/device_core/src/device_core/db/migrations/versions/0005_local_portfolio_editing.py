"""local portfolio editing schema: device.local_pin, manual_holding

Revision ID: 0005
Revises: 0004
Create Date: 2026-08-02

Hand-written (no autogenerate), mirroring device_core/db/models.py
column-for-column, same convention as 0001/0002/0003/0004.
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0005"
down_revision: Union[str, None] = "0004"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("device", sa.Column("local_pin", sa.String(length=16), nullable=True))

    op.create_table(
        "manual_holding",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("symbol", sa.String(length=16), nullable=False, index=True),
        sa.Column("target_qty", sa.Float(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("symbol", name="uq_manual_holding_symbol"),
    )


def downgrade() -> None:
    op.drop_table("manual_holding")
    op.drop_column("device", "local_pin")
