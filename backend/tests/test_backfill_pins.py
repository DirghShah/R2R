"""The one-off that re-pins places stranded by the Google Places outage.

Between 10 and 30 October every searchText call returned 403, so the pipeline
saved each place with lat NULL. Nothing retries those: geocoding runs once,
during analysis. This covers the three cases that decide whether the script is
safe to point at production.
"""
from __future__ import annotations

# Imported first: it sets DATABASE_URL before any app module binds the engine.
from tests.test_api_flow import client  # noqa: F401

from app.db import session  # noqa: E402
from app.models import Place  # noqa: E402
from scripts import backfill_pins  # noqa: E402
from worker import geocode  # noqa: E402


def _add(name, *, lat=None, lng=None, source=None, external=None):
    db = session()
    try:
        p = Place(name=name, category="restaurant", lat=lat, lng=lng,
                  location_source=source, external_place_id=external)
        db.add(p)
        db.commit()
        return p.id
    finally:
        db.close()


def _get(pid):
    db = session()
    try:
        return db.get(Place, pid)
    finally:
        db.close()


def test_hand_placed_pins_are_never_offered(client):
    """The coordinates a person set by hand are the best ones in the database."""
    _add("Hand Placed", lat=33.0, lng=-96.0, source="user")
    # A hand-placed row that somehow lost its coordinates must still be spared.
    _add("Hand Placed, No Coords", source="user")
    _add("Stranded")

    db = session()
    try:
        names = {p.name for p in backfill_pins.unpinned(db)}
    finally:
        db.close()

    assert "Stranded" in names
    assert "Hand Placed" not in names
    assert "Hand Placed, No Coords" not in names


def test_apply_writes_coordinates(client, monkeypatch, capsys):
    pid = _add("Walloons")
    monkeypatch.setattr(geocode, "geocode", lambda ep, **kw: geocode.GeocodeResult(
        external_place_id="gp:walloons", name=ep.name, lat=32.78, lng=-96.80,
        address="1 Main St, Dallas, TX, USA", region="TX", city="Dallas", country="USA"))
    monkeypatch.setattr(backfill_pins.sys, "argv",
                        ["backfill_pins.py", "--apply", "--delay", "0"])

    assert backfill_pins.main() == 0
    place = _get(pid)
    assert (place.lat, place.lng) == (32.78, -96.80)
    assert place.external_place_id == "gp:walloons"


def test_dry_run_writes_nothing(client, monkeypatch):
    pid = _add("Dinette")
    monkeypatch.setattr(geocode, "geocode", lambda ep, **kw: geocode.GeocodeResult(
        external_place_id="gp:dinette", name=ep.name, lat=32.75, lng=-97.33,
        city="Fort Worth", country="USA"))
    monkeypatch.setattr(backfill_pins.sys, "argv", ["backfill_pins.py", "--delay", "0"])

    assert backfill_pins.main() == 0
    assert _get(pid).lat is None, "dry run wrote to the database"


def test_a_duplicate_venue_gets_the_pin_but_not_the_id(client, monkeypatch):
    """Adopting an external id another row already holds would split the venue
    in two. Take the coordinates, leave the id, say so."""
    _add("Uncle Zhou Restaurant", lat=33.02, lng=-96.69, external="gp:unclezhou")
    pid = _add("Uncle Zhou's")
    monkeypatch.setattr(geocode, "geocode", lambda ep, **kw: geocode.GeocodeResult(
        external_place_id="gp:unclezhou", name=ep.name, lat=33.02, lng=-96.69,
        city="Plano", country="USA"))
    monkeypatch.setattr(backfill_pins.sys, "argv",
                        ["backfill_pins.py", "--apply", "--delay", "0"])

    assert backfill_pins.main() == 0
    place = _get(pid)
    assert place.lat == 33.02, "the pin is the point of the exercise"
    assert place.external_place_id is None, "took an id that belongs to another row"
