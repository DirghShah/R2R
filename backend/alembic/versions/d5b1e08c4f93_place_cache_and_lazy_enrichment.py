"""Remember what we already looked up, and what we haven't enriched yet.

Two billed calls used to run for every extracted place, every time, even for a
restaurant already sitting in the database from someone else's reel.

`places.enriched_at` records whether rating/photos/hours have ever been
fetched — null means the pin exists but nobody has opened it, so nothing was
paid for enrichment. `geocode_misses` remembers a name that found nothing, so a
viral reel naming an unknown venue isn't re-searched by every person who shares
it.

Existing places are backfilled as enriched, because they were: every one of them
went through the old path that always called Place Details.

Revision ID: d5b1e08c4f93
Revises: c3a9e51d7b42
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "d5b1e08c4f93"
down_revision = "c3a9e51d7b42"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("places", sa.Column("enriched_at", sa.DateTime(timezone=True), nullable=True))

    # Everything already in the table was enriched by the old always-both-calls
    # path. Left null they would all re-enrich on first open, which is a bill
    # for data already stored.
    op.execute(
        "UPDATE places SET enriched_at = COALESCE(last_verified_at, CURRENT_TIMESTAMP)"
    )

    op.create_table(
        "geocode_misses",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column("name_key", sa.String(), nullable=False),
        sa.Column("city_key", sa.String(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("name_key", "city_key", name="uq_geocode_miss"),
    )
    op.create_index("ix_geocode_misses_name_key", "geocode_misses", ["name_key"])
    op.create_index("ix_geocode_misses_city_key", "geocode_misses", ["city_key"])


def downgrade() -> None:
    op.drop_table("geocode_misses")
    op.drop_column("places", "enriched_at")
