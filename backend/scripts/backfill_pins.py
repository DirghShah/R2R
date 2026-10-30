#!/usr/bin/env python3
"""Re-geocode places that were saved while Google Places was returning 403.

Between 10 and 30 October every `places:searchText` call failed, so the
pipeline saved each place with `lat` NULL. Those rows are real — they carry
the name, the tips and the reel they came from — but they are invisible on the
map, and nothing re-tries them: geocoding happens once, during analysis.

`POST /places/{id}/enrich` cannot fix them either. It fetches ratings and
photos for a place that is already identified, and these were never
identified, so there is no external id to enrich from.

Dry run unless you pass --apply:

    python3 scripts/backfill_pins.py              # list what would change
    python3 scripts/backfill_pins.py --apply      # write it
    python3 scripts/backfill_pins.py --limit 5 --apply   # try a few first

Two things it deliberately will not do.

It never touches a pin somebody placed by hand (`location_source == "user"`).
Those are the most carefully-set coordinates in the database.

And when geocoding returns an `external_place_id` that already belongs to a
different row, it writes the coordinates but leaves the id alone, and reports
the pair. That means the same venue exists twice, and merging it is a repoint
of every UserPlace plus a delete — the shape of change that broke production
once already. The pin is what matters here; the merge is a separate decision
made with eyes open.
"""

import argparse
import sys
import time
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sqlalchemy import select  # noqa: E402

from app.db import session  # noqa: E402
from app.models import Place  # noqa: E402
from worker import geocode  # noqa: E402
from worker.pipeline import _get_or_create_city  # noqa: E402


def unpinned(db, limit=None):
    """Places with no coordinates that nobody has placed by hand."""
    q = (
        select(Place)
        .where(Place.lat.is_(None))
        .where((Place.location_source.is_(None)) | (Place.location_source != "user"))
        .order_by(Place.name)
    )
    if limit:
        q = q.limit(limit)
    return list(db.scalars(q))


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--apply", action="store_true", help="write the results (default: dry run)")
    ap.add_argument("--limit", type=int, help="only process this many places")
    ap.add_argument("--delay", type=float, default=1.1,
                    help="seconds between lookups; the default keeps the "
                         "Nominatim fallback inside its 1/sec policy (1.1)")
    args = ap.parse_args()

    db = session()
    try:
        rows = unpinned(db, args.limit)
        if not rows:
            print("Nothing to do — every place has coordinates.")
            return 0

        print(f"{len(rows)} place(s) without coordinates"
              f"{'' if args.apply else '  [DRY RUN — nothing will be written]'}\n")

        fixed = failed = collided = 0
        for i, place in enumerate(rows, 1):
            city_name = place.city.name if place.city else None
            ep = SimpleNamespace(name=place.name, city=city_name, country=None,
                                 category=place.category, cuisine=place.cuisine)

            geo = geocode.geocode(ep)
            if geo.lat is None:
                failed += 1
                print(f"  {i:>3}. ✗ {place.name}  ({city_name or 'no city'}) — not found")
                time.sleep(args.delay)
                continue

            # Would adopting this external id duplicate another row?
            clash = None
            if geo.external_place_id:
                clash = db.scalar(
                    select(Place).where(
                        Place.external_place_id == geo.external_place_id,
                        Place.id != place.id,
                    )
                )

            note = ""
            if clash is not None:
                collided += 1
                note = f"  ⚠ same venue as {clash.name!r} ({clash.id}) — id left unset"
            fixed += 1
            print(f"  {i:>3}. ✓ {place.name}  →  {geo.lat:.5f}, {geo.lng:.5f}"
                  f"  {geo.address or ''}{note}")

            if args.apply:
                place.lat = geo.lat
                place.lng = geo.lng
                place.address = geo.address
                region = geo.region or geocode.region_from_address(geo.address)
                place.region = region
                city = _get_or_create_city(db, geo.city or city_name, geo.country, region=region)
                if city is not None:
                    place.city = city
                if clash is None and geo.external_place_id:
                    place.external_place_id = geo.external_place_id
                    place.rating = geo.rating
                    place.review_count = geo.review_count
                    place.price_level = geo.price_level
                    place.photos = geo.photos or None
                    place.hours = geo.hours
                    place.phone = geo.phone
                    place.google_maps_url = geo.google_maps_url
                db.commit()

            time.sleep(args.delay)

        print(f"\n  pinned: {fixed}    still unfindable: {failed}    "
              f"duplicate venues flagged: {collided}")
        if not args.apply and fixed:
            print("\n  Dry run — nothing written. Re-run with --apply.")
        return 0
    finally:
        db.close()


if __name__ == "__main__":
    raise SystemExit(main())
