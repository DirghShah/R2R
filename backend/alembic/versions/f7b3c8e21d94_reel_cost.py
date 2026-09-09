"""Store what each analysis cost.

Previously the per-reel cost was only printed to the worker log, so the only
way to answer "what am I spending" was to grep a stream that rotates. A column
makes it a query — and makes the saving from rejecting non-food reels early
measurable rather than theoretical.

Revision ID: f7b3c8e21d94
Revises: e4a7c2f19b83
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "f7b3c8e21d94"
down_revision = "e4a7c2f19b83"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Nullable, not defaulted to 0: reels analysed before this column existed
    # have an unknown cost, and recording that as zero would understate every
    # historical total.
    op.add_column("reel_sources", sa.Column("cost_usd", sa.Float(), nullable=True))


def downgrade() -> None:
    op.drop_column("reel_sources", "cost_usd")
