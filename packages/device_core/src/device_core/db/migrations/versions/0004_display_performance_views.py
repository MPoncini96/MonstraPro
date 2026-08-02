"""display idle-screen rotation schema: position_snapshot, bot_value_snapshot

Revision ID: 0004
Revises: 0003
Create Date: 2026-08-02

Hand-written (no autogenerate), mirroring device_core/db/models.py
column-for-column, same convention as 0001/0002/0003.
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0004"
down_revision: Union[str, None] = "0003"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "position_snapshot",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("ts", sa.DateTime(timezone=True), nullable=False, index=True),
        sa.Column("symbol", sa.String(length=16), nullable=False, index=True),
        sa.Column("qty", sa.Float(), nullable=False),
        sa.Column("avg_entry_price", sa.Float(), nullable=False),
        sa.Column("current_price", sa.Float(), nullable=False),
        sa.Column("market_value", sa.Float(), nullable=False),
        sa.Column("unrealized_pl", sa.Float(), nullable=False),
        sa.Column("unrealized_plpc", sa.Float(), nullable=False),
        sa.Column("unrealized_intraday_plpc", sa.Float(), nullable=False),
    )

    op.create_table(
        "bot_value_snapshot",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("ts", sa.DateTime(timezone=True), nullable=False, index=True),
        sa.Column("bot_slug", sa.String(length=64), nullable=False, index=True),
        sa.Column("value", sa.Float(), nullable=False),
    )


def downgrade() -> None:
    op.drop_table("bot_value_snapshot")
    op.drop_table("position_snapshot")
