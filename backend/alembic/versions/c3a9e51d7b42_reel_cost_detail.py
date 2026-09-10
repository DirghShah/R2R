"""Keep the ingredients behind each reel's cost, not just the total.

A single number can't be broken down after the fact and can't be re-priced when
a vendor changes its rates, which makes "what am I spending, and on what"
unanswerable for everything already analysed.

Revision ID: c3a9e51d7b42
Revises: b8d2f30c5a17
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "c3a9e51d7b42"
down_revision = "b8d2f30c5a17"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("reel_sources", sa.Column("cost_detail", sa.JSON(), nullable=True))


def downgrade() -> None:
    op.drop_column("reel_sources", "cost_detail")
