"""strategy_config.bot_type: the engine family (force/aptet/draco), separate
from bot_slug's per-instance identity.

Revision ID: 0007
Revises: 0006
Create Date: 2026-08-03

Hand-written (no autogenerate), mirroring device_core/db/models.py
column-for-column, same convention as 0001-0006.
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0007"
down_revision: Union[str, None] = "0006"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("strategy_config", sa.Column("bot_type", sa.String(length=32), nullable=True))


def downgrade() -> None:
    op.drop_column("strategy_config", "bot_type")
