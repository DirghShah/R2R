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
    collections = sa.table(
        "collections", sa.column("id", sa.String), sa.column("user_id", sa.String),
        sa.column("city_id", sa.String), sa.column("category", sa.String),
        sa.column("title", sa.String),
    )

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

    def usage(city_id: str) -> int:
        return bind.execute(
            sa.select(sa.func.count()).select_from(places).where(places.c.city_id == city_id)
        ).scalar() or 0

    # Rows that name a country are preferred as survivors, then the most-used
    # ones — so the row that lives on carries the most information and is the
    # one most places already point at.
    ordered = sorted(rows, key=lambda r: (r[2] is not None, usage(r[0])), reverse=True)

    by_name: dict[str, list[str]] = {}  # canonical name -> surviving city ids

    for city_id, name, country in ordered:
        canonical = _normalize(name, regions.get(city_id)) or name
        winner = survivors.get((canonical, country))
        if winner is None and country is None:
            # A row with no country is the same place as a uniquely-named row
            # that has one. This is where the bare "New York" holding a single
            # place came from, and keying on (name, country) alone left it
            # sitting next to the New York it belongs to.
            candidates = by_name.get(canonical, [])
            if len(candidates) == 1:
                winner = candidates[0]
        if winner is None:
            survivors[(canonical, country)] = city_id
            by_name.setdefault(canonical, []).append(city_id)
            if canonical != name:
                renames.append((city_id, canonical))
        else:
            merges.append((city_id, winner))

    for loser, winner in merges:
        bind.execute(
            places.update().where(places.c.city_id == loser).values(city_id=winner)
        )

        # collections has a unique constraint on (user_id, city_id, category),
        # so repointing blindly collides whenever the same person had a list of
        # the same category in both cities — a New York cafe list and a
        # Brooklyn cafe list, which is precisely what merging is for.
        #
        # A collection carries no membership: it is a derived label, and its
        # places are found through the city and category it names. So a loser
        # that would collide is redundant rather than data, and is deleted. The
        # winner's set is re-read per merge because an earlier loser may already
        # have added to it.
        taken = {
            (user_id, category)
            for user_id, category in bind.execute(
                sa.select(collections.c.user_id, collections.c.category)
                .where(collections.c.city_id == winner)
            ).all()
        }
        for coll_id, user_id, category in bind.execute(
            sa.select(collections.c.id, collections.c.user_id, collections.c.category)
            .where(collections.c.city_id == loser)
        ).all():
            if (user_id, category) in taken:
                bind.execute(collections.delete().where(collections.c.id == coll_id))
            else:
                bind.execute(
                    collections.update()
                    .where(collections.c.id == coll_id)
                    .values(city_id=winner)
                )
                taken.add((user_id, category))

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

    # A collection's title is built from its city's name, so every merged or
    # renamed city leaves stale titles behind ("Brooklyn cafés" on New York).
    from worker.pipeline import _CATEGORY_TITLES

    for (canonical, _), city_id in survivors.items():
        for coll_id, category in bind.execute(
            sa.select(collections.c.id, collections.c.category)
            .where(collections.c.city_id == city_id)
        ).all():
            title = f"{canonical} {_CATEGORY_TITLES.get(category, 'saved places')}"
            bind.execute(
                collections.update().where(collections.c.id == coll_id).values(title=title)
            )

    print(f"[migration] merged {len(merges)} duplicate cities, renamed {len(renames)}")


def downgrade() -> None:
    # Nothing to restore to: the rows that were merged away are gone, and which
    # place belonged to which spelling was never recorded anywhere else.
    pass
