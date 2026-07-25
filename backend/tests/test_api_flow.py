"""End-to-end API tests over SQLite: reel dedupe, place dedupe, delete.

These run without Redis, Anthropic or a geocoder — the queue is stubbed and the
analysis is simulated by calling the pipeline's persistence helpers directly.
"""
from __future__ import annotations

import os
import tempfile

import pytest

os.environ.setdefault("ENVIRONMENT", "dev")
_DB_FD, _DB_PATH = tempfile.mkstemp(suffix=".db")
os.environ["DATABASE_URL"] = f"sqlite:///{_DB_PATH}"

from fastapi.testclient import TestClient  # noqa: E402

from app.db import Base, engine, session  # noqa: E402
from app.main import app  # noqa: E402
from app.models import Place, ReelSource, UserPlace  # noqa: E402
from worker import pipeline, queue  # noqa: E402

REEL_A = "https://www.instagram.com/reel/AAAAAAAAAAA/"
REEL_B = "https://www.instagram.com/reel/BBBBBBBBBBB/"


class _Extracted:
    """Minimal stand-in for worker.extract.ExtractedPlace."""

    def __init__(self, name: str, category: str = "cafe", city: str = "Dallas") -> None:
        self.name = name
        self.category = category
        self.cuisine = None
        self.city = city
        self.country = "USA"
        self.neighborhood = None
        self.description = "desc"
        self.tips = ["tip"]
        self.what_to_order = []
        self.vibe = []
        self.instagram_handle = None
        self.website = None
        self.hours_hint = None
        self.price_level = None
        self.confidence = 0.9


@pytest.fixture
def client(monkeypatch):
    Base.metadata.drop_all(bind=engine)
    Base.metadata.create_all(bind=engine)
    # The queue is not under test; record what would have been enqueued.
    enqueued: list[tuple[str, str]] = []
    monkeypatch.setattr(queue, "enqueue_analyze", lambda r, u: enqueued.append((r, u)))
    monkeypatch.setattr("app.routers.reels.enqueue_analyze", lambda r, u: enqueued.append((r, u)))
    with TestClient(app) as c:
        token = c.post("/auth/apple", json={"identity_token": "dev:tester"}).json()["access_token"]
        c.headers["Authorization"] = f"Bearer {token}"
        c.enqueued = enqueued  # type: ignore[attr-defined]
        yield c


def _analyze(reel_id: str, user_id: str, names: list[str]) -> int:
    """Simulate the AI+geocode stage: persist `names` as places for the reel."""
    db = session()
    try:
        reel = db.get(ReelSource, reel_id)
        saved = 0
        for name in names:
            ep = _Extracted(name)
            geo = pipeline.geocode.GeocodeResult(
                name=name, lat=32.7, lng=-96.8, address="1 Main St, Dallas, TX, USA",
                region="TX", city="Dallas", country="USA",
                external_place_id=f"gp:{name.lower()}",
            )
            place = pipeline._upsert_place(db, ep, geo)
            _, created = pipeline._upsert_user_place(db, user_id, place, reel, ep)
            pipeline._bucket_collection(db, user_id, place)
            if created:
                saved += 1
        reel.status = "done"
        db.commit()
        return saved
    finally:
        db.close()


def _first_user() -> str:
    from app.models import User

    db = session()
    try:
        return db.scalars(pipeline.select(User.id)).first()
    finally:
        db.close()


# --- reel dedupe ----------------------------------------------------------


def test_resubmitting_a_pending_reel_does_not_enqueue_twice(client):
    first = client.post("/reels", json={"url": REEL_A}).json()
    assert first["status"] == "pending"
    assert len(client.enqueued) == 1

    second = client.post("/reels", json={"url": REEL_A}).json()
    assert second["reel_id"] == first["reel_id"]
    assert second["already_analyzed"] is True
    assert len(client.enqueued) == 1, "a second job was queued for an in-flight reel"


def test_resubmitting_an_analyzed_reel_reuses_the_stored_analysis(client):
    reel_id = client.post("/reels", json={"url": REEL_A}).json()["reel_id"]
    _analyze(reel_id, _first_user(), ["Kung Fu Tea"])
    client.enqueued.clear()

    again = client.post("/reels", json={"url": REEL_A}).json()
    assert again["already_analyzed"] is True
    assert again["status"] == "done"
    assert again["place_count"] == 1
    assert client.enqueued == [], "re-analyzed a reel we already had results for"
    assert len(client.get("/places").json()) == 1


def test_duplicate_submission_is_not_billed_to_the_quota(client):
    from app.models import User

    client.post("/reels", json={"url": REEL_A})
    for _ in range(3):
        client.post("/reels", json={"url": REEL_A})

    db = session()
    try:
        assert db.scalars(pipeline.select(User.reels_this_month)).first() == 1
    finally:
        db.close()


def test_a_url_variant_of_the_same_reel_is_recognised(client):
    first = client.post("/reels", json={"url": REEL_A}).json()
    variant = client.post("/reels", json={"url": REEL_A + "?igshid=abc123"}).json()
    assert variant["reel_id"] == first["reel_id"]


# --- place dedupe ---------------------------------------------------------


def test_same_place_from_two_reels_makes_one_pin(client):
    reel_a = client.post("/reels", json={"url": REEL_A}).json()["reel_id"]
    user = _first_user()
    _analyze(reel_a, user, ["Kung Fu Tea", "Cafe Duro"])

    reel_b = client.post("/reels", json={"url": REEL_B}).json()["reel_id"]
    new_pins = _analyze(reel_b, user, ["Kung Fu Tea", "Sanjuana"])

    places = client.get("/places").json()
    names = sorted(p["place"]["name"] for p in places)
    assert names == ["Cafe Duro", "Kung Fu Tea", "Sanjuana"], "a venue was pinned twice"
    assert new_pins == 1, "the already-pinned venue counted as newly saved"


def test_the_second_reel_is_recorded_as_a_source_on_the_existing_pin(client):
    reel_a = client.post("/reels", json={"url": REEL_A}).json()["reel_id"]
    user = _first_user()
    _analyze(reel_a, user, ["Kung Fu Tea"])
    reel_b = client.post("/reels", json={"url": REEL_B}).json()["reel_id"]
    _analyze(reel_b, user, ["Kung Fu Tea"])

    db = session()
    try:
        up = db.scalars(pipeline.select(UserPlace)).first()
        assert sorted(up.sources) == sorted([reel_a, reel_b])
    finally:
        db.close()

    # ...and both reels still report the place in the activity feed.
    activity = {a["reel_id"]: a["place_count"] for a in client.get("/reels").json()}
    assert activity[reel_a] == 1
    assert activity[reel_b] == 1


def test_unpinned_places_dedupe_on_name_within_a_city(client):
    """No external place id (geocoder found nothing) must not clone the row."""
    reel = client.post("/reels", json={"url": REEL_A}).json()["reel_id"]
    user = _first_user()
    db = session()
    try:
        reel_row = db.get(ReelSource, reel)
        for _ in range(2):
            ep = _Extracted("Nameless Diner")
            geo = pipeline.geocode.GeocodeResult(name="Nameless Diner", city="Dallas", country="USA")
            place = pipeline._upsert_place(db, ep, geo)
            pipeline._upsert_user_place(db, user, place, reel_row, ep)
        db.commit()
        assert len(db.scalars(pipeline.select(Place)).all()) == 1
    finally:
        db.close()


# --- delete ---------------------------------------------------------------


def test_delete_removes_the_pin_and_its_empty_list(client):
    reel = client.post("/reels", json={"url": REEL_A}).json()["reel_id"]
    _analyze(reel, _first_user(), ["Kung Fu Tea"])

    saved = client.get("/places").json()
    assert len(saved) == 1
    assert client.get("/lists").json() != []

    assert client.delete(f"/places/{saved[0]['id']}").status_code == 204
    assert client.get("/places").json() == []
    assert client.get("/lists").json() == [], "an empty city list was left behind"


def test_delete_keeps_the_other_pins(client):
    reel = client.post("/reels", json={"url": REEL_A}).json()["reel_id"]
    _analyze(reel, _first_user(), ["Kung Fu Tea", "Cafe Duro"])
    saved = client.get("/places").json()

    client.delete(f"/places/{saved[0]['id']}")
    remaining = client.get("/places").json()
    assert len(remaining) == 1
    assert remaining[0]["id"] == saved[1]["id"]


def test_delete_is_404_for_someone_elses_place(client):
    reel = client.post("/reels", json={"url": REEL_A}).json()["reel_id"]
    _analyze(reel, _first_user(), ["Kung Fu Tea"])
    mine = client.get("/places").json()[0]["id"]

    other = TestClient(app)
    token = other.post("/auth/apple", json={"identity_token": "dev:intruder"}).json()["access_token"]
    other.headers["Authorization"] = f"Bearer {token}"
    assert other.delete(f"/places/{mine}").status_code == 404
    assert len(client.get("/places").json()) == 1


def test_deleted_place_comes_back_if_the_reel_is_submitted_again(client):
    """Deleting is per-user; the cached analysis is untouched, so a re-submit
    re-links the place rather than paying for a second analysis."""
    reel = client.post("/reels", json={"url": REEL_A}).json()["reel_id"]
    user = _first_user()
    _analyze(reel, user, ["Kung Fu Tea"])
    client.delete(f"/places/{client.get('/places').json()[0]['id']}")
    client.enqueued.clear()

    again = client.post("/reels", json={"url": REEL_A}).json()
    assert again["already_analyzed"] is True
    assert client.enqueued == [(reel, user)], "should re-link, not re-analyze"
