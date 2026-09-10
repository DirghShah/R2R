"""Collapse the duplicate cities free-text city names created.

The city on a place was whatever the model wrote or the geocoder returned, and
both are inconsistent about the same place. One New York map arrived as six
lists: "New York, NY", "Brooklyn, NY", "Long Island City, NY", "Manhattan, NY",
"New York" and "New York City, NY".

This canonicalises every existing city name the same way the pipeline now does,
merges rows that land on the same name, repoints places and collections at the
survivor, and deletes what's left over. It also backfills a missing region from
the rest of the city, since a place with no region reads as its own city in the
app even after the names agree.

Revision ID: b8d2f30c5a17
Revises: a1c4e7f92b06
"""
from __future__ import annotations

from collections import Counter

import sqlalchemy as sa
from alembic import op

revision = "b8d2f30c5a17"
down_revision = "a1c4e7f92b06"
branch_labels = None
depends_on = None


def _normalize(name, region):
    # Imported lazily: a migration must not fail to load because an unrelated
    # worker import broke.
    from worker.geocode import normalize_city

    return normalize_city(name, region)


def upgrade() -> None:
    bind = op.get_bind()

    cities = sa.table(
        "cities", sa.column("id", sa.String), sa.column("name", sa.String),
        sa.column("country", sa.String),
    )
    places = sa.table(
        "places", sa.column("id", sa.String), sa.column("city_id", sa.String),
        sa.column("region", sa.String),
    )
    collections = sa.table("collections", sa.column("city_id", sa.String))

    rows = bind.execute(sa.select(cities.c.id, cities.c.name, cities.c.country)).all()
    if not rows:
        return

    # The region a city's places actually carry, which is what decides whether
    # "Brooklyn" is the New York borough or the village in Ohio.
    regions: dict[str, str | None] = {}
    for city_id, _, _ in rows:
        found = bind.execute(
            sa.select(places.c.region).where(
                places.c.city_id == city_id, places.c.region.isnot(None)
            )
        ).scalars().all()
        regions[city_id] = Counter(found).most_common(1)[0][0] if found else None

    # canonical (name, country) -> the city row that keeps it
    survivors: dict[tuple[str, str | None], str] = {}
    renames: list[tuple[str, str]] = []   # (city_id, new_name)
    merges: list[tuple[str, str]] = []    # (loser_id, winner_id)

    # Most-used first, so the row that survives is the one most places already
    # point at — fewer rows to repoint, and its id stays stable for clients.
    def usage(city_id: str) -> int:
        return bind.execute(
            sa.select(sa.func.count()).select_from(places).where(places.c.city_id == city_id)
        ).scalar() or 0

    for city_id, name, country in sorted(rows, key=lambda r: -usage(r[0])):
        canonical = _normalize(name, regions.get(city_id)) or name
        key = (canonical, country)
        winner = survivors.get(key)
        if winner is None:
            survivors[key] = city_id
            if canonical != name:
                renames.append((city_id, canonical))
        else:
            merges.append((city_id, winner))

    for loser, winner in merges:
        bind.execute(
            places.update().where(places.c.city_id == loser).values(city_id=winner)
        )
        bind.execute(
            collections.update().where(collections.c.city_id == loser).values(city_id=winner)
        )
        bind.execute(cities.delete().where(cities.c.id == loser))

    for city_id, canonical in renames:
        bind.execute(cities.update().where(cities.c.id == city_id).values(name=canonical))

    # Backfill region from the city's own majority, for places that have none.
    for (_, _), city_id in survivors.items():
        found = bind.execute(
            sa.select(places.c.region).where(
                places.c.city_id == city_id, places.c.region.isnot(None)
            )
        ).scalars().all()
        if not found:
            continue
        majority = Counter(found).most_common(1)[0][0]
        bind.execute(
            places.update()
            .where(places.c.city_id == city_id, places.c.region.is_(None))
            .values(region=majority)
        )

    print(f"[migration] merged {len(merges)} duplicate cities, renamed {len(renames)}")


def downgrade() -> None:
    # Nothing to restore to: the rows that were merged away are gone, and which
    # place belonged to which spelling was never recorded anywhere else.
    pass
