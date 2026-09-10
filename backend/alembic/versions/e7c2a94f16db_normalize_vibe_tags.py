"""Snap existing vibe tags onto the closed list.

Vibe was free text, so one idea arrived as several strings — "cozy",
"intimate", "chill vibes" — and nothing matched anything. Vibe search reasons
over these tags, so every place saved before the list existed would be invisible
to a search that mentions its own atmosphere.

Tags that map onto nothing are dropped rather than kept. An unrecognised vibe
carries no meaning for search or filtering, and keeping it would put a chip on
the map that matches nothing.

Revision ID: e7c2a94f16db
Revises: d5b1e08c4f93
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "e7c2a94f16db"
down_revision = "d5b1e08c4f93"
branch_labels = None
depends_on = None


def upgrade() -> None:
    from worker.extract import normalize_vibes

    bind = op.get_bind()
    table = sa.table(
        "user_places", sa.column("id", sa.String), sa.column("vibe", sa.JSON)
    )
    rows = bind.execute(
        sa.select(table.c.id, table.c.vibe).where(table.c.vibe.isnot(None))
    ).all()

    changed = 0
    for row_id, vibe in rows:
        if not isinstance(vibe, list) or not vibe:
            continue
        canonical = normalize_vibes(vibe)
        if canonical != vibe:
            bind.execute(
                table.update().where(table.c.id == row_id).values(vibe=canonical or None)
            )
            changed += 1

    print(f"[migration] normalised {changed} of {len(rows)} vibe tag lists")


def downgrade() -> None:
    # The original free-text tags were not recorded anywhere else.
    pass
