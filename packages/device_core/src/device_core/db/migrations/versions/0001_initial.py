"""initial schema: device, alpaca_credentials, strategy_config,
portfolio_allocation, signal, execution_log, device_event

Revision ID: 0001
Revises:
Create Date: 2026-07-25

Hand-written (no autogenerate) so this migration is exactly what's
reviewed here, mirroring device_core/db/models.py column-for-column.
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0001"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "device",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("serial", sa.String(length=64), nullable=False, unique=True),
        sa.Column("activation_code_hash", sa.String(length=128), nullable=True),
        sa.Column("activated_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("owner_ref", sa.String(length=128), nullable=True),
        sa.Column("disclosures_accepted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("software_version", sa.String(length=32), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )

    op.create_table(
        "alpaca_credentials",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("mode", sa.String(length=16), nullable=False, index=True),
        sa.Column("api_key_encrypted", sa.Text(), nullable=False),
        sa.Column("api_secret_encrypted", sa.Text(), nullable=False),
        sa.Column("base_url", sa.String(length=255), nullable=False),
        sa.Column("connected_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("mode", name="uq_alpaca_credentials_mode"),
    )

    op.create_table(
        "strategy_config",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("bot_slug", sa.String(length=64), nullable=False, index=True),
        sa.Column("display_name", sa.String(length=128), nullable=True),
        sa.Column("params_json", sa.JSON(), nullable=True),
        sa.Column("target_allocation_json", sa.JSON(), nullable=True),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("source", sa.String(length=32), nullable=False, server_default="local"),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("bot_slug", name="uq_strategy_config_bot_slug"),
    )

    op.create_table(
        "portfolio_allocation",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("bot_slug", sa.String(length=64), nullable=False, index=True),
        sa.Column("ts", sa.DateTime(timezone=True), nullable=False, index=True),
        sa.Column("target_weights_json", sa.JSON(), nullable=True),
        sa.Column("current_weights_json", sa.JSON(), nullable=True),
    )

    op.create_table(
        "signal",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("bot_id", sa.String(length=64), nullable=False, index=True),
        sa.Column("bot_type", sa.String(length=64), nullable=False, index=True),
        sa.Column("ts", sa.DateTime(timezone=True), nullable=False, index=True),
        sa.Column("signal", sa.String(length=32), nullable=False),
        sa.Column("note", sa.Text(), nullable=True),
        sa.Column("payload_json", sa.JSON(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )

    op.create_table(
        "execution_log",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("ts", sa.DateTime(timezone=True), nullable=False, index=True),
        sa.Column("level", sa.String(length=16), nullable=False),
        sa.Column("component", sa.String(length=64), nullable=False),
        sa.Column("message", sa.Text(), nullable=False),
        sa.Column("context_json", sa.JSON(), nullable=True),
    )

    op.create_table(
        "device_event",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("ts", sa.DateTime(timezone=True), nullable=False, index=True),
        sa.Column("type", sa.String(length=64), nullable=False, index=True),
        sa.Column("severity", sa.String(length=16), nullable=False, server_default="info"),
        sa.Column("payload_json", sa.JSON(), nullable=True),
        sa.Column("consumed_at", sa.DateTime(timezone=True), nullable=True, index=True),
        sa.Column("consumed_by", sa.String(length=64), nullable=True),
    )


def downgrade() -> None:
    op.drop_table("device_event")
    op.drop_table("execution_log")
    op.drop_table("signal")
    op.drop_table("portfolio_allocation")
    op.drop_table("strategy_config")
    op.drop_table("alpaca_credentials")
    op.drop_table("device")
