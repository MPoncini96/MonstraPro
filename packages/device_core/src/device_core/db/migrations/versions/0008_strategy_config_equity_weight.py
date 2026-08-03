"""strategy_config.equity_weight: this bot's relative share of the account
when trading_worker nets multiple active bots' trades together.

Revision ID: 0008
Revises: 0007
Create Date: 2026-08-03

Hand-written (no autogenerate), mirroring device_core/db/models.py
column-for-column, same convention as 0001-0007.
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0008"
down_revision: Union[str, None] = "0007"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("strategy_config", sa.Column("equity_weight", sa.Float(), nullable=True))


def downgrade() -> None:
    op.drop_column("strategy_config", "equity_weight")
