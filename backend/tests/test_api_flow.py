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
    monkeypatch.setattr(queue, "enqueue_analyze",
                        lambda r, u, m=None: enqueued.append((r, u)))
    monkeypatch.setattr("app.routers.reels.enqueue_analyze",
                        lambda r, u, m=None: enqueued.append((r, u)))
    with TestClient(app) as c:
        token = c.post("/auth/apple", json={"identity_token": "dev:tester"}).json()["access_token"]
        c.headers["Authorization"] = f"Bearer {token}"
        c.enqueued = enqueued  # type: ignore[attr-defined]
        yield c


def _analyze(reel_id: str, user_id: str, names: list[str], map_id: str | None = None) -> int:
    """Simulate the AI+geocode stage: persist `names` as places for the reel."""
    from app.maps import personal_map

    db = session()
    try:
        reel = db.get(ReelSource, reel_id)
        target = map_id or personal_map(db, user_id).id
        saved = 0
        for name in names:
            ep = _Extracted(name)
            geo = pipeline.geocode.GeocodeResult(
                name=name, lat=32.7, lng=-96.8, address="1 Main St, Dallas, TX, USA",
                region="TX", city="Dallas", country="USA",
                external_place_id=f"gp:{name.lower()}",
            )
            place = pipeline._upsert_place(db, ep, geo)
            _, created = pipeline._upsert_user_place(db, user_id, place, reel, ep, target)
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
        from app.maps import personal_map

        reel_row = db.get(ReelSource, reel)
        target = personal_map(db, user).id
        for _ in range(2):
            ep = _Extracted("Nameless Diner")
            geo = pipeline.geocode.GeocodeResult(name="Nameless Diner", city="Dallas", country="USA")
            place = pipeline._upsert_place(db, ep, geo)
            pipeline._upsert_user_place(db, user, place, reel_row, ep, target)
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


# --- hand-placed locations ------------------------------------------------


def _unpinned(client, name: str = "Nameless Diner") -> str:
    """Save a place the geocoder couldn't resolve; returns its UserPlace id."""
    reel = client.post("/reels", json={"url": REEL_A}).json()["reel_id"]
    db = session()
    try:
        reel_row = db.get(ReelSource, reel)
        from app.maps import personal_map

        ep = _Extracted(name)
        geo = pipeline.geocode.GeocodeResult(name=name, city="Dallas", country="USA")
        place = pipeline._upsert_place(db, ep, geo)
        pipeline._upsert_user_place(
            db, _first_user(), place, reel_row, ep, personal_map(db, _first_user()).id
        )
        reel_row.status = "done"
        db.commit()
    finally:
        db.close()
    return client.get("/places").json()[0]["id"]


def test_place_with_no_coordinates_is_still_listed(client):
    _unpinned(client)
    saved = client.get("/places").json()
    assert len(saved) == 1
    assert saved[0]["place"]["lat"] is None, "the geocoder should not have guessed"


def test_setting_a_location_by_hand_pins_the_place(client):
    up_id = _unpinned(client)
    body = {"lat": 32.9, "lng": -96.9, "address": "1023 E Trinity Mills Rd, Carrollton, TX 75006, USA"}
    resp = client.patch(f"/places/{up_id}/location", json=body)
    assert resp.status_code == 200

    place = resp.json()["place"]
    assert (place["lat"], place["lng"]) == (32.9, -96.9)
    assert place["location_source"] == "user"
    assert place["region"] == "TX", "region should be derived from the new address"
    assert client.get("/places").json()[0]["place"]["lat"] == 32.9


def test_reanalysis_never_moves_a_hand_placed_pin(client):
    up_id = _unpinned(client)
    client.patch(f"/places/{up_id}/location", json={"lat": 32.9, "lng": -96.9})

    # The reel gets analyzed again and the geocoder still finds nothing.
    db = session()
    try:
        reel_row = db.scalars(pipeline.select(ReelSource)).first()
        ep = _Extracted("Nameless Diner")
        geo = pipeline.geocode.GeocodeResult(name="Nameless Diner", city="Dallas", country="USA")
        pipeline._upsert_place(db, ep, geo)
        db.commit()
    finally:
        db.close()

    place = client.get("/places").json()[0]["place"]
    assert (place["lat"], place["lng"]) == (32.9, -96.9), "re-analysis clobbered the user's pin"


def test_out_of_range_coordinates_are_rejected(client):
    up_id = _unpinned(client)
    assert client.patch(f"/places/{up_id}/location", json={"lat": 99.0, "lng": 0.0}).status_code == 422


def test_cannot_set_the_location_of_someone_elses_place(client):
    up_id = _unpinned(client)
    other = TestClient(app)
    token = other.post("/auth/apple", json={"identity_token": "dev:intruder"}).json()["access_token"]
    other.headers["Authorization"] = f"Bearer {token}"
    resp = other.patch(f"/places/{up_id}/location", json={"lat": 1.0, "lng": 1.0})
    assert resp.status_code == 404


# --- monthly quota --------------------------------------------------------


def _set_quota(count: int, period_start) -> None:
    from app.models import User

    db = session()
    try:
        user = db.scalars(pipeline.select(User)).first()
        user.reels_this_month = count
        user.quota_period_start = period_start
        db.commit()
    finally:
        db.close()


def _quota() -> int:
    from app.models import User

    db = session()
    try:
        return db.scalars(pipeline.select(User.reels_this_month)).first()
    finally:
        db.close()


def test_quota_resets_when_the_month_turns_over(client):
    """Without a period anchor the counter only climbs and locks the user out."""
    from datetime import datetime, timedelta, timezone

    client.post("/reels", json={"url": REEL_A})
    last_month = datetime.now(timezone.utc).replace(day=1) - timedelta(days=1)
    _set_quota(1000, last_month)

    resp = client.post("/reels", json={"url": REEL_B})
    assert resp.status_code == 200, "a stale counter still blocked a new month"
    assert _quota() == 1, "the counter should restart, not keep climbing"


def test_quota_still_blocks_within_the_same_month(client):
    from datetime import datetime, timezone

    client.post("/reels", json={"url": REEL_A})
    _set_quota(1000, datetime.now(timezone.utc))
    assert client.post("/reels", json={"url": REEL_B}).status_code == 402


# --- hardening ------------------------------------------------------------


def test_reel_status_is_not_readable_by_another_user(client):
    """Without an ownership join, any authenticated user could read any reel."""
    reel_id = client.post("/reels", json={"url": REEL_A}).json()["reel_id"]

    other = TestClient(app)
    token = other.post("/auth/apple", json={"identity_token": "dev:snooper"}).json()["access_token"]
    other.headers["Authorization"] = f"Bearer {token}"
    assert other.get(f"/reels/{reel_id}").status_code == 404
    # ...while the owner still sees it.
    assert client.get(f"/reels/{reel_id}").status_code == 200


def test_rate_limit_blocks_a_burst_of_submissions(client, monkeypatch):
    """POST /reels is a direct line to the AI + geocoding bill."""
    from app import ratelimit

    counts: dict[str, int] = {}

    class _FakeRedis:
        def incr(self, key):
            counts[key] = counts.get(key, 0) + 1
            return counts[key]

        def expire(self, key, seconds):
            return True

    monkeypatch.setattr(ratelimit, "_redis", lambda: _FakeRedis())
    monkeypatch.setattr(ratelimit.settings, "rate_limit_reels_per_hour", 3)

    for i in range(3):
        assert client.post("/reels", json={"url": f"{REEL_A[:-1]}{i}/"}).status_code == 200
    assert client.post("/reels", json={"url": REEL_B}).status_code == 429


def test_rate_limit_fails_open_when_redis_is_down(client, monkeypatch):
    """A limiter that takes the API down with it is worse than none."""
    from app import ratelimit

    def _boom():
        raise ConnectionError("redis unreachable")

    monkeypatch.setattr(ratelimit, "_redis", _boom)
    assert client.post("/reels", json={"url": REEL_A}).status_code == 200
