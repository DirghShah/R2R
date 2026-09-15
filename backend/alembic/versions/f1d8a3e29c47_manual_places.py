"""Let a saved place exist without a reel behind it.

Until now every saved place came from a reel, so the link to one was required.
Adding a place by searching for it has no reel to point at — and the first thing
a new user does, before they have shared anything, is exactly that.

Revision ID: f1d8a3e29c47
Revises: e7c2a94f16db
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "f1d8a3e29c47"
down_revision = "e7c2a94f16db"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("user_places") as batch:
        batch.alter_column("reel_source_id", existing_type=sa.String(), nullable=True)


def downgrade() -> None:
    # Would fail on any manually added place, which is the correct outcome:
    # there is no reel to invent for it.
    with op.batch_alter_table("user_places") as batch:
        batch.alter_column("reel_source_id", existing_type=sa.String(), nullable=False)
