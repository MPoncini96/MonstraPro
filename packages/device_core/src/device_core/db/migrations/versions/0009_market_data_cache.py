"""market_data_cache: cached OHLC bars per (symbol, slide), for display's
per-stock 1h/1d/1y view. Originally scoped in ARCHITECTURE.md section 7 and
deferred at migration 0004; see device_core/db/models.py's Phase 7 note for
why it's needed now.

Revision ID: 0009
Revises: 0008
Create Date: 2026-08-04

Hand-written (no autogenerate), mirroring device_core/db/models.py
column-for-column, same convention as 0001-0008.
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0009"
down_revision: Union[str, None] = "0008"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "market_data_cache",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("symbol", sa.String(length=16), nullable=False, index=True),
        sa.Column("slide", sa.String(length=8), nullable=False),
        sa.Column("bars_json", sa.JSON(), nullable=False),
        sa.Column("fetched_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("symbol", "slide", name="uq_market_data_cache_symbol_slide"),
    )


def downgrade() -> None:
    op.drop_table("market_data_cache")
