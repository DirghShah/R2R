"""Not paying twice for the same restaurant.

Every extracted place used to cost two billed Google calls — a search to find
the venue and a details call for its rating and photos — every time, even for a
restaurant already resolved from somebody else's reel. Food reels cluster hard
on the same venues, so the same place arrives over and over.

The dangerous half is the cache *hit*: merging two different restaurants is
permanent and affects everyone, so most of what follows is about the cases that
must NOT match.
"""
from __future__ import annotations

# Imported first: it sets DATABASE_URL before any app module binds the engine.
from tests.test_api_flow import _Extracted, client  # noqa: F401

from app.config import settings  # noqa: E402
from app.db import session  # noqa: E402
from app.models import City, GeocodeMiss, Place  # noqa: E402
from worker import geocode, pipeline  # noqa: E402


def _pin(name: str, *, city: str = "Dallas", category: str = "cafe",
         region: str = "TX") -> Place:
    """Put a resolved place in the database, as an earlier reel would have.

    `region` matters: the write path normalises the city knowing it, which is
    what turns "Brooklyn" into "New York" before it is stored.
    """
    db = session()
    try:
        ep = _Extracted(name, category=category, city=city)
        geo = geocode.GeocodeResult(
            name=name, lat=32.7, lng=-96.8, address=f"1 Main St, {city}, {region}, USA",
            region=region, city=city, country="USA",
            external_place_id=f"gp:{name.lower()}-{city.lower()}",
        )
        place = pipeline._upsert_place(db, ep, geo)
        db.commit()
        return db.get(Place, place.id)
    finally:
        db.close()


def _lookup(name: str, *, city: str = "Dallas", category: str = "cafe") -> Place | None:
    db = session()
    try:
        found = pipeline._cached_place(db, _Extracted(name, category=category, city=city))
        return db.get(Place, found.id) if found else None
    finally:
        db.close()


# --- hits -----------------------------------------------------------------


def test_the_same_restaurant_from_a_second_reel_costs_nothing(client):
    original = _pin("Kung Fu Tea")
    assert _lookup("Kung Fu Tea").id == original.id


def test_spelling_and_punctuation_differences_still_match(client):
    original = _pin("Joe's Pizza")
    for variant in ["Joes Pizza", "JOE'S PIZZA", "  Joe's  Pizza  "]:
        assert _lookup(variant).id == original.id, f"{variant!r} should be the same venue"


def test_a_borough_and_its_city_are_one_place(client):
    """City normalisation feeds the cache key, so a place saved under Brooklyn
    is found again when the next reel calls it Manhattan."""
    original = _pin("Di Fara", city="Brooklyn", region="NY")
    # Stored as New York, because the write knew the region.
    assert original.city.name == "New York"
    # Found again whichever borough the next reel happens to name.
    assert _lookup("Di Fara", city="New York").id == original.id
    assert _lookup("Di Fara", city="Brooklyn").id == original.id
    assert _lookup("Di Fara", city="Manhattan").id == original.id


# --- the misses that matter -----------------------------------------------


def test_two_venues_with_one_name_in_one_city_do_not_merge(client):
    """A bar and a bakery both called Sunrise are different businesses, and
    merging them is permanent and affects everyone who saved either."""
    _pin("Sunrise", category="cafe")
    assert _lookup("Sunrise", category="bar") is None


def test_the_same_name_in_another_city_does_not_merge(client):
    _pin("Joe's Pizza", city="Dallas")
    assert _lookup("Joe's Pizza", city="Austin") is None


def test_a_merely_similar_name_does_not_merge(client):
    _pin("Tacos El Rey")
    assert _lookup("Tacos El Sol") is None


def test_an_unpinned_place_is_never_reused(client):
    """Reusing a place the geocoder failed on saves nothing and propagates the
    failure to everyone who shares that reel later."""
    db = session()
    try:
        city = City(name="Dallas", country="USA")
        db.add(city)
        db.flush()
        # No lat/lng and no external id: the lookup ran and found nothing.
        db.add(Place(name="Ghost Kitchen", category="cafe", city_id=city.id))
        db.commit()
    finally:
        db.close()
    assert _lookup("Ghost Kitchen") is None


def test_the_cache_can_be_switched_off(client, monkeypatch):
    original = _pin("Kung Fu Tea")
    assert _lookup("Kung Fu Tea").id == original.id
    monkeypatch.setattr(settings, "place_cache_enabled", False)
    assert _lookup("Kung Fu Tea") is None


# --- the negative cache ---------------------------------------------------


def test_a_name_that_found_nothing_is_not_searched_again(client):
    db = session()
    try:
        ep = _Extracted("Nowhere Cafe")
        assert pipeline._geocode_recently_missed(db, ep) is False
        pipeline._record_geocode_miss(db, ep)
        db.commit()
        assert pipeline._geocode_recently_missed(db, ep) is True
    finally:
        db.close()


def test_the_miss_expires(client, monkeypatch):
    """Bounded on purpose — Google does add places, and a permanent 'no' would
    mean a venue could never be pinned once it had failed."""
    db = session()
    try:
        ep = _Extracted("Opening Soon")
        pipeline._record_geocode_miss(db, ep)
        db.commit()
        monkeypatch.setattr(settings, "geocode_miss_ttl_days", 0)
        assert pipeline._geocode_recently_missed(db, ep) is False
    finally:
        db.close()


def test_recording_the_same_miss_twice_does_not_error(client):
    db = session()
    try:
        ep = _Extracted("Nowhere Cafe")
        pipeline._record_geocode_miss(db, ep)
        pipeline._record_geocode_miss(db, ep)
        db.commit()
        rows = db.query(GeocodeMiss).filter(
            GeocodeMiss.name_key == geocode.match_key("Nowhere Cafe")
        ).count()
        assert rows == 1
    finally:
        db.close()


# --- enrichment on open ---------------------------------------------------


def test_a_freshly_enriched_place_is_not_looked_up_again(client, monkeypatch):
    """The endpoint is called every time a place is opened, so it has to be
    free when there is nothing to fetch."""
    from datetime import datetime, timezone

    from app.routers.places import _enrichment_is_fresh

    place = _pin("Kung Fu Tea")
    db = session()
    try:
        row = db.get(Place, place.id)
        assert row.enriched_at is not None, "the eager path records enrichment"
        assert _enrichment_is_fresh(row) is True
        row.enriched_at = datetime(2020, 1, 1, tzinfo=timezone.utc)
        db.commit()
        assert _enrichment_is_fresh(row) is False, "stale hours must be refetched"
    finally:
        db.close()


def test_a_pin_made_without_enrichment_is_marked_as_owing_it(client):
    """With lazy enrichment on, the search result alone pins the place and
    `enriched_at` stays null until somebody opens it."""
    db = session()
    try:
        ep = _Extracted("Search Only")
        geo = geocode.GeocodeResult(
            name="Search Only", lat=32.7, lng=-96.8, city="Dallas", region="TX",
            external_place_id="gp:searchonly", enriched=False,
        )
        place = pipeline._upsert_place(db, ep, geo)
        db.commit()
        assert db.get(Place, place.id).enriched_at is None
    finally:
        db.close()


def test_the_cost_log_does_not_bill_places_the_cache_supplied(client):
    """Billing every place would report a saving that never reaches the log."""
    from app.config import settings as cfg

    both = pipeline._cost_detail(searched=3, in_tok=1000, out_tok=100, places_saved=5)
    assert both["places"] == 5
    assert both["places_searched"] == 3
    if cfg.geocoder != "nominatim":
        assert both["geocode_usd"] < cfg.google_cost_per_place * 5
