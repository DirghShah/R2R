"""Backfill Place.region from stored addresses

Places saved before the region column existed have no state code, so their
city lists read "Dallas" instead of "Dallas, TX". Parsing it out of the address
we already stored avoids re-geocoding them.

Revision ID: b2f1a4c70d31
Revises: c1020c8fd9ac
Create Date: 2026-07-26
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = 'b2f1a4c70d31'
down_revision = 'c1020c8fd9ac'
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Reuse the same parser the geocoder and the iOS client use, so all three
    # agree on what counts as a region.
    from worker.geocode import region_from_address

    conn = op.get_bind()
    rows = conn.execute(
        sa.text("SELECT id, address FROM places WHERE region IS NULL AND address IS NOT NULL")
    ).fetchall()
    for place_id, address in rows:
        region = region_from_address(address)
        if region:
            conn.execute(
                sa.text("UPDATE places SET region = :r WHERE id = :i"),
                {"r": region, "i": place_id},
            )


def downgrade() -> None:
    # A backfill has nothing meaningful to undo — the column itself is dropped
    # by the baseline's downgrade.
    pass
