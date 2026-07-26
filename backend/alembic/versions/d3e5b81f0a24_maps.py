"""Maps: every user gets a personal map, places move onto maps

The dedupe invariant moves from (user_id, place_id) to (map_id, place_id).

Ordering matters here. The old table's DB constraint was
(user_id, place_id, reel_source_id) while the *application* enforced one row
per (user_id, place_id), so real data can contain rows that would violate the
new (map_id, place_id) uniqueness. Duplicates are collapsed BEFORE the
constraint is added, or the migration fails on production data.

Revision ID: d3e5b81f0a24
Revises: c910378e12b8
"""
from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone

import sqlalchemy as sa
from alembic import op

revision = 'd3e5b81f0a24'
down_revision = 'c910378e12b8'
branch_labels = None
depends_on = None


def upgrade() -> None:
    conn = op.get_bind()

    op.create_table(
        'maps',
        sa.Column('id', sa.String(), nullable=False),
        sa.Column('name', sa.String(), nullable=False),
        sa.Column('emoji', sa.String(), nullable=True),
        sa.Column('owner_id', sa.String(), nullable=False),
        sa.Column('is_personal', sa.Boolean(), nullable=False),
        sa.Column('invite_code', sa.String(), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(['owner_id'], ['users.id']),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index(op.f('ix_maps_owner_id'), 'maps', ['owner_id'])
    op.create_index(op.f('ix_maps_invite_code'), 'maps', ['invite_code'], unique=True)

    op.create_table(
        'map_members',
        sa.Column('id', sa.String(), nullable=False),
        sa.Column('map_id', sa.String(), nullable=False),
        sa.Column('user_id', sa.String(), nullable=False),
        sa.Column('role', sa.String(), nullable=False),
        sa.Column('joined_at', sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(['map_id'], ['maps.id']),
        sa.ForeignKeyConstraint(['user_id'], ['users.id']),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('map_id', 'user_id', name='uq_map_member'),
    )
    op.create_index(op.f('ix_map_members_map_id'), 'map_members', ['map_id'])
    op.create_index(op.f('ix_map_members_user_id'), 'map_members', ['user_id'])

    # --- 1. a personal map per existing user --------------------------------
    now = datetime.now(timezone.utc)
    personal: dict[str, str] = {}
    for (user_id,) in conn.execute(sa.text("SELECT id FROM users")).fetchall():
        map_id = str(uuid.uuid4())
        personal[user_id] = map_id
        conn.execute(
            sa.text(
                "INSERT INTO maps (id, name, emoji, owner_id, is_personal, created_at) "
                "VALUES (:id, :name, :emoji, :owner, :personal, :created)"
            ),
            {"id": map_id, "name": "My Map", "emoji": "📍", "owner": user_id,
             "personal": True, "created": now},
        )
        conn.execute(
            sa.text(
                "INSERT INTO map_members (id, map_id, user_id, role, joined_at) "
                "VALUES (:id, :map, :user, 'owner', :joined)"
            ),
            {"id": str(uuid.uuid4()), "map": map_id, "user": user_id, "joined": now},
        )

    # --- 2. collapse duplicates BEFORE the new constraint exists ------------
    # Keep the earliest row per (user, place) and merge the others' sources
    # into it, so a venue saved from two reels keeps both attributions.
    rows = conn.execute(sa.text(
        "SELECT id, user_id, place_id, sources, saved_at FROM user_places "
        "ORDER BY saved_at ASC"
    )).fetchall()
    keep: dict[tuple[str, str], tuple[str, list]] = {}
    drop: list[str] = []
    for row_id, user_id, place_id, sources, _saved in rows:
        parsed = sources if isinstance(sources, list) else (json.loads(sources) if sources else [])
        key = (user_id, place_id)
        if key in keep:
            kept_id, kept_sources = keep[key]
            merged = list(dict.fromkeys([*kept_sources, *parsed]))
            keep[key] = (kept_id, merged)
            drop.append(row_id)
        else:
            keep[key] = (row_id, parsed)

    for kept_id, merged in keep.values():
        conn.execute(
            sa.text("UPDATE user_places SET sources = :s WHERE id = :i"),
            {"s": json.dumps(merged), "i": kept_id},
        )
    for row_id in drop:
        conn.execute(sa.text("DELETE FROM user_places WHERE id = :i"), {"i": row_id})

    # --- 3. point every remaining place at its owner's personal map ---------
    with op.batch_alter_table('user_places') as batch:
        batch.add_column(sa.Column('map_id', sa.String(), nullable=True))

    for user_id, map_id in personal.items():
        conn.execute(
            sa.text("UPDATE user_places SET map_id = :m WHERE user_id = :u"),
            {"m": map_id, "u": user_id},
        )

    # --- 4. only now is it safe to enforce the invariant --------------------
    with op.batch_alter_table('user_places') as batch:
        batch.alter_column('map_id', existing_type=sa.String(), nullable=False)
        batch.create_index(op.f('ix_user_places_map_id'), ['map_id'])
        batch.create_foreign_key('fk_user_places_map', 'maps', ['map_id'], ['id'])
        try:
            batch.drop_constraint('uq_user_place_reel', type_='unique')
        except Exception:  # noqa: BLE001 — SQLite may not have named it
            pass
        batch.create_unique_constraint('uq_map_place', ['map_id', 'place_id'])


def downgrade() -> None:
    with op.batch_alter_table('user_places') as batch:
        batch.drop_constraint('uq_map_place', type_='unique')
        batch.drop_column('map_id')
    op.drop_table('map_members')
    op.drop_table('maps')
