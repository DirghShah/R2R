"""Adding a place by searching for it, rather than sharing a reel of it.

Two first-time testers opened the app and wanted to build a list of restaurants
they had already been to. One of them doesn't use social media at all, so every
reel-shaped path was closed to him and the map stayed blank. The app was
unusable until you had done homework somewhere else.

The other half of this is what makes searching inside Nosh worth doing at all:
the canonical place row is shared, so a place you merely looked up arrives
already carrying what earlier reels said about it.
"""
from __future__ import annotations

# Imported first: it sets DATABASE_URL before any app module binds the engine.
from tests.test_api_flow import REEL_A, _analyze, _first_user, client  # noqa: F401

from app.db import session  # noqa: E402
from app.models import Place, UserPlace  # noqa: E402
from worker import geocode  # noqa: E402


def _resolved(name="Tartine Bakery", pid="gp:tartine"):
    return geocode.GeocodeResult(
        external_place_id=pid, name=name, lat=37.76, lng=-122.42,
        address="600 Guerrero St, San Francisco, CA, USA", region="CA",
        city="San Francisco", country="USA", rating=4.5, review_count=900,
    )


def test_a_searched_place_becomes_an_ordinary_pin(client, monkeypatch):
    monkeypatch.setattr(geocode, "resolve", lambda _pid: _resolved())

    body = client.post("/places/add", json={"place_id": "tartine"}).json()
    assert body["place"]["name"] == "Tartine Bakery"
    assert body["place"]["lat"] == 37.76
    assert body["added_manually"] is True
    # It shows up in the normal list, on the normal map, like anything else.
    assert any(p["place"]["name"] == "Tartine Bakery" for p in client.get("/places").json())


def test_adding_the_same_place_twice_is_not_an_error(client, monkeypatch):
    """Asking for a place to be on a map it is already on is a satisfied
    request, not a failure."""
    monkeypatch.setattr(geocode, "resolve", lambda _pid: _resolved())
    first = client.post("/places/add", json={"place_id": "tartine"}).json()
    second = client.post("/places/add", json={"place_id": "tartine"})
    assert second.status_code == 201
    assert second.json()["id"] == first["id"]


def test_a_place_already_known_is_not_looked_up_again(client, monkeypatch):
    """The canonical row is shared, so a venue somebody's reel already resolved
    costs nothing to add by hand."""
    monkeypatch.setattr(geocode, "resolve", lambda _pid: _resolved())
    client.post("/places/add", json={"place_id": "tartine"})

    def _explode(_pid):
        raise AssertionError("should not have paid for a second lookup")

    monkeypatch.setattr(geocode, "resolve", _explode)
    # A different map, so a new UserPlace — but the same canonical place.
    other = client.post("/maps", json={"name": "Been to"}).json()
    resp = client.post("/places/add", json={"place_id": "tartine", "map_id": other["id"]})
    assert resp.status_code == 201


def test_a_lookup_that_fails_says_so(client, monkeypatch):
    monkeypatch.setattr(geocode, "resolve", lambda _pid: None)
    assert client.post("/places/add", json={"place_id": "nonsense"}).status_code == 404


def test_you_cannot_add_to_a_map_you_are_not_in(client, monkeypatch):
    from fastapi.testclient import TestClient
    from app.main import app

    monkeypatch.setattr(geocode, "resolve", lambda _pid: _resolved())
    mine = client.get("/maps").json()[0]["id"]

    stranger = TestClient(app)
    token = stranger.post("/auth/apple", json={"identity_token": "dev:outsider"}).json()
    stranger.headers["Authorization"] = f"Bearer {token['access_token']}"
    resp = stranger.post("/places/add", json={"place_id": "tartine", "map_id": mine})
    assert resp.status_code in (403, 404)


# --- what makes searching inside Nosh worth doing -------------------------


def test_a_searched_place_inherits_what_earlier_reels_said(client, monkeypatch):
    """The whole argument for searching here rather than in Maps: someone
    else's reel already worked out what to order."""
    reel = client.post("/reels", json={"url": REEL_A}).json()["reel_id"]
    _analyze(reel, _first_user(), ["Kung Fu Tea"])

    db = session()
    try:
        place = db.scalar(select_place(db, "Kung Fu Tea"))
        up = db.scalars(
            __import__("sqlalchemy").select(UserPlace)
            .where(UserPlace.place_id == place.id)
        ).first()
        up.description = "Milk tea worth the queue."
        up.what_to_order = ["Brown sugar boba"]
        up.tips = ["Cash only after 9pm"]
        external = place.external_place_id
        db.commit()
    finally:
        db.close()

    monkeypatch.setattr(geocode, "resolve", lambda _pid: _resolved())
    other = client.post("/maps", json={"name": "Been to"}).json()
    body = client.post(
        "/places/add",
        json={"place_id": external.removeprefix("gp:"), "map_id": other["id"]},
    ).json()

    assert body["description"] == "Milk tea worth the queue."
    assert body["what_to_order"] == ["Brown sugar boba"]
    assert body["tips"] == ["Cash only after 9pm"]


def test_a_place_carries_the_reels_that_mention_it(client):
    reel = client.post("/reels", json={"url": REEL_A}).json()["reel_id"]
    _analyze(reel, _first_user(), ["Kung Fu Tea"])

    saved = client.get("/places").json()
    row = next(p for p in saved if p["place"]["name"] == "Kung Fu Tea")
    # Its own reel is not listed back at it — that is already the source.
    assert all(m["url"] != row["reel_url"] for m in row["seen_in_reels"])


def test_a_place_nobody_has_shared_carries_no_reels(client, monkeypatch):
    monkeypatch.setattr(geocode, "resolve", lambda _pid: _resolved())
    body = client.post("/places/add", json={"place_id": "tartine"}).json()
    assert body["seen_in_reels"] == []
    assert body["description"] is None


def select_place(db, name):
    from sqlalchemy import select
    return select(Place).where(Place.name == name)


# --- suggestions ----------------------------------------------------------


def test_suggestions_come_back_as_rows_not_places(client, monkeypatch):
    """Nothing is looked up while typing — a suggestion is a name and an id."""
    monkeypatch.setattr(geocode, "suggest", lambda q, lat=None, lng=None: [
        geocode.Suggestion(place_id="gp:a", name="Tartine Bakery",
                           detail="600 Guerrero St"),
    ])
    body = client.get("/places/suggest?q=tarti").json()
    assert body[0]["name"] == "Tartine Bakery"
    assert body[0]["detail"] == "600 Guerrero St"


def test_a_short_query_never_reaches_google(monkeypatch):
    monkeypatch.setattr(geocode.settings, "geocoder", "google")
    monkeypatch.setattr(geocode.settings, "google_places_api_key", "key")

    def _explode(*_a, **_kw):
        raise AssertionError("should not have called out")

    monkeypatch.setattr(geocode.httpx, "post", _explode)
    assert geocode.suggest("t") == []
    assert geocode.suggest("") == []


# --- the first thirty seconds --------------------------------------------


def test_the_example_costs_nothing_and_lands_real_pins(client, monkeypatch):
    """A new person has no reels and an empty map. The example is the only path
    that gives them the app's actual output with no work and no spend."""
    from app.config import settings
    from app.db import session as _session
    from app.models import ReelSource

    reel = client.post("/reels", json={"url": REEL_A}).json()["reel_id"]
    _analyze(reel, _first_user(), ["Kung Fu Tea", "Otto's"])
    monkeypatch.setattr(settings, "example_reel_url", REEL_A)

    before = len(client.enqueued)
    body = client.post("/reels/example").json()

    assert body["status"] == "done"
    assert body["place_count"] == 2
    # Nothing was queued: no fetch, no model call, no geocoding.
    assert len(client.enqueued) == before


def test_no_example_configured_means_the_button_is_not_offered(client, monkeypatch):
    from app.config import settings

    monkeypatch.setattr(settings, "example_reel_url", None)
    assert client.post("/reels/example").status_code == 404


def test_an_example_that_was_never_analysed_is_refused(client, monkeypatch):
    """Analysing on demand would be slow, cost money, and could fail in front
    of somebody in their first thirty seconds."""
    from app.config import settings

    monkeypatch.setattr(settings, "example_reel_url",
                        "https://www.instagram.com/reel/neverseen/")
    assert client.post("/reels/example").status_code == 404
