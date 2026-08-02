"""trading_worker schema: order, bot_state, account_snapshot

Revision ID: 0002
Revises: 0001
Create Date: 2026-08-01

Hand-written (no autogenerate), mirroring device_core/db/models.py
column-for-column, same convention as 0001.
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0002"
down_revision: Union[str, None] = "0001"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "order",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("bot_slug", sa.String(length=64), nullable=False, index=True),
        sa.Column("symbol", sa.String(length=16), nullable=False, index=True),
        sa.Column("side", sa.String(length=8), nullable=False),
        sa.Column("qty", sa.Float(), nullable=True),
        sa.Column("notional", sa.Float(), nullable=True),
        sa.Column("order_type", sa.String(length=16), nullable=False, server_default="market"),
        sa.Column("status", sa.String(length=32), nullable=False, index=True),
        sa.Column("alpaca_order_id", sa.String(length=64), nullable=True, index=True),
        sa.Column("submitted_at", sa.DateTime(timezone=True), nullable=False, index=True),
        sa.Column("filled_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("raw_response_json", sa.JSON(), nullable=True),
    )

    op.create_table(
        "bot_state",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("bot_slug", sa.String(length=64), nullable=False, index=True),
        sa.Column("state_json", sa.JSON(), nullable=True),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("bot_slug", name="uq_bot_state_bot_slug"),
    )

    op.create_table(
        "account_snapshot",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("ts", sa.DateTime(timezone=True), nullable=False, index=True),
        sa.Column("equity", sa.Float(), nullable=False),
        sa.Column("cash", sa.Float(), nullable=False),
    )


def downgrade() -> None:
    op.drop_table("account_snapshot")
    op.drop_table("bot_state")
    op.drop_table("order")
