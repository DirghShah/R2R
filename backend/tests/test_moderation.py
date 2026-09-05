"""Reporting, blocking, and recovery from a worker that died mid-job.

The moderation half exists for App Store Guideline 1.2, which requires an app
with user-generated content to offer both reporting and blocking. The stale-reel
half is a real outage we hit: the worker was killed and every reel it was
holding showed "Analyzing…" in the app forever.
"""
from __future__ import annotations

# Imported first: it sets DATABASE_URL before any app module binds the engine.
from tests.test_api_flow import REEL_A, _analyze, _first_user, client  # noqa: F401

from datetime import datetime, timedelta, timezone  # noqa: E402

from tests.test_maps import _user, _user_id  # noqa: E402

from app.db import session  # noqa: E402
from app.models import ReelSource  # noqa: E402


# --- reporting ------------------------------------------------------------


def test_reporting_a_map_is_recorded(client):
    trip = client.post("/maps", json={"name": "Dallas Eats"}).json()
    r = client.post("/reports", json={
        "target_type": "map", "target_id": trip["id"],
        "reason": "offensive", "note": "the name is a slur",
    })
    assert r.status_code == 201
    assert r.json()["status"] == "open", "a report must land in a reviewable state"


def test_reporting_a_user_is_recorded(client):
    friend = _user("dev:reported")
    r = client.post("/reports", json={
        "target_type": "user", "target_id": _user_id(friend), "reason": "harassment",
    })
    assert r.status_code == 201


def test_a_report_needs_a_real_target(client):
    """Otherwise the queue fills with reports nobody can action."""
    r = client.post("/reports", json={
        "target_type": "map", "target_id": "does-not-exist", "reason": "spam",
    })
    assert r.status_code == 404


def test_junk_target_types_and_reasons_are_rejected(client):
    trip = client.post("/maps", json={"name": "Trip"}).json()
    assert client.post("/reports", json={
        "target_type": "banana", "target_id": trip["id"], "reason": "spam",
    }).status_code == 400
    assert client.post("/reports", json={
        "target_type": "map", "target_id": trip["id"], "reason": "vibes",
    }).status_code == 400


# --- blocking -------------------------------------------------------------


def test_blocking_hides_that_person_from_the_member_list(client):
    trip = client.post("/maps", json={"name": "Trip"}).json()
    code = client.post(f"/maps/{trip['id']}/invite").json()["invite_code"]
    friend = _user("dev:blockme")
    friend.post(f"/maps/join/{code}")
    friend_id = _user_id(friend)

    assert len(client.get(f"/maps/{trip['id']}/members").json()) == 2
    client.post("/blocks", json={"user_id": friend_id})
    assert len(client.get(f"/maps/{trip['id']}/members").json()) == 1


def test_blocking_hides_the_places_they_added(client):
    trip = client.post("/maps", json={"name": "Trip"}).json()
    code = client.post(f"/maps/{trip['id']}/invite").json()["invite_code"]
    friend = _user("dev:adder")
    friend.post(f"/maps/join/{code}")
    friend_id = _user_id(friend)

    reel = friend.post("/reels", json={"url": REEL_A, "map_id": trip["id"]}).json()["reel_id"]
    _analyze(reel, friend_id, ["Kung Fu Tea"], map_id=trip["id"])

    assert any(p["place"]["name"] == "Kung Fu Tea" for p in client.get("/places").json())
    client.post("/blocks", json={"user_id": friend_id})
    assert not any(p["place"]["name"] == "Kung Fu Tea" for p in client.get("/places").json())


def test_unblocking_restores_everything(client):
    """Blocking filters at read time rather than deleting, so it's reversible."""
    trip = client.post("/maps", json={"name": "Trip"}).json()
    code = client.post(f"/maps/{trip['id']}/invite").json()["invite_code"]
    friend = _user("dev:temporary")
    friend.post(f"/maps/join/{code}")
    friend_id = _user_id(friend)

    client.post("/blocks", json={"user_id": friend_id})
    assert len(client.get(f"/maps/{trip['id']}/members").json()) == 1

    assert client.delete(f"/blocks/{friend_id}").status_code == 204
    assert len(client.get(f"/maps/{trip['id']}/members").json()) == 2


def test_blocking_does_not_remove_anyone_from_the_map(client):
    """A block that ejected people would be a griefing tool — the owner decides
    membership. The blocked person keeps their access."""
    trip = client.post("/maps", json={"name": "Trip"}).json()
    code = client.post(f"/maps/{trip['id']}/invite").json()["invite_code"]
    friend = _user("dev:stillhere")
    friend.post(f"/maps/join/{code}")

    client.post("/blocks", json={"user_id": _user_id(friend)})
    assert any(m["id"] == trip["id"] for m in friend.get("/maps").json())


def test_you_cannot_block_yourself(client):
    assert client.post("/blocks", json={"user_id": _first_user()}).status_code == 400


def test_blocking_twice_is_harmless(client):
    friend = _user("dev:twiceblocked")
    fid = _user_id(friend)
    client.post("/blocks", json={"user_id": fid})
    client.post("/blocks", json={"user_id": fid})
    assert len(client.get("/blocks").json()) == 1


# --- stuck reels ----------------------------------------------------------


def _age_reel(reel_id: str, minutes: int) -> None:
    db = session()
    try:
        reel = db.get(ReelSource, reel_id)
        reel.status = "processing"
        reel.started_at = datetime.now(timezone.utc) - timedelta(minutes=minutes)
        db.commit()
    finally:
        db.close()


def test_a_reel_still_working_is_not_re_queued(client):
    reel_id = client.post("/reels", json={"url": REEL_A}).json()["reel_id"]
    _age_reel(reel_id, minutes=2)
    before = len(client.enqueued)

    again = client.post("/reels", json={"url": REEL_A}).json()
    assert again["status"] == "processing"
    assert len(client.enqueued) == before, "a busy reel must not be re-run"


def test_a_reel_abandoned_by_a_dead_worker_is_re_queued(client):
    """The outage this exists for: the worker was killed mid-job, so the reel
    sat at 'processing' with nothing left to finish it and the app showed
    'Analyzing…' forever."""
    reel_id = client.post("/reels", json={"url": REEL_A}).json()["reel_id"]
    _age_reel(reel_id, minutes=45)
    before = len(client.enqueued)

    again = client.post("/reels", json={"url": REEL_A}).json()
    assert again["status"] == "pending", "a stuck reel must be recoverable"
    assert len(client.enqueued) == before + 1

    db = session()
    try:
        assert db.get(ReelSource, reel_id).started_at is None, "the stale marker is cleared"
    finally:
        db.close()
