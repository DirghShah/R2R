"""Reporting, blocking, and a start timestamp for stuck reels.

Two unrelated needs, one migration because they land together:

- `reports` / `blocks` — App Store Guideline 1.2 requires an app with
  user-generated content to offer both. Map names, display names and the places
  someone adds to a shared map are that content.

- `reel_sources.started_at` — a worker killed mid-job leaves status="processing"
  committed forever. Without a marker for when the run began there is no way to
  distinguish a stuck reel from one still working, so the app showed
  "Analyzing…" permanently with no recovery.

Revision ID: e4a7c2f19b83
Revises: d3e5b81f0a24
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = 'e4a7c2f19b83'
down_revision = 'd3e5b81f0a24'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "reel_sources",
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
    )

    op.create_table(
        "reports",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column("reporter_id", sa.String(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("target_type", sa.String(), nullable=False),
        sa.Column("target_id", sa.String(), nullable=False),
        sa.Column("reason", sa.String(), nullable=False),
        sa.Column("note", sa.String(), nullable=True),
        sa.Column("status", sa.String(), nullable=False, server_default="open"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_reports_reporter_id", "reports", ["reporter_id"])
    op.create_index("ix_reports_target_id", "reports", ["target_id"])

    op.create_table(
        "blocks",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column("user_id", sa.String(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("blocked_user_id", sa.String(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("user_id", "blocked_user_id", name="uq_block_pair"),
    )
    op.create_index("ix_blocks_user_id", "blocks", ["user_id"])
    op.create_index("ix_blocks_blocked_user_id", "blocks", ["blocked_user_id"])


def downgrade() -> None:
    op.drop_index("ix_blocks_blocked_user_id", table_name="blocks")
    op.drop_index("ix_blocks_user_id", table_name="blocks")
    op.drop_table("blocks")
    op.drop_index("ix_reports_target_id", table_name="reports")
    op.drop_index("ix_reports_reporter_id", table_name="reports")
    op.drop_table("reports")
    op.drop_column("reel_sources", "started_at")
