"""The same place, and the same reel, across two maps.

Maps are independent collections. A venue on your "Dallas" map has nothing to
do with whether it should appear on "Date nights" — but the guard that decides
whether re-sharing a known reel does anything was counting per *user* rather
than per *map*, so the second map silently got nothing.
"""
from __future__ import annotations

# Imported first: it sets DATABASE_URL before any app module binds the engine.
from tests.test_api_flow import REEL_A, REEL_B, _analyze, _first_user, client  # noqa: F401

from tests.test_maps import _user, _user_id  # noqa: E402


def _places_on(client, map_id):  # noqa: F811
    return [p["place"]["name"] for p in client.get("/places").json()
            if p["map_id"] == map_id]


def test_the_same_reel_shared_to_a_second_map_lands_there(client):
    """The reported bug. Sharing a known reel into a new map found the *first*
    map's pin, concluded there was nothing to do, and added nothing — while
    reporting its places were "on your map"."""
    personal = client.get("/maps").json()[0]["id"]
    reel = client.post("/reels", json={"url": REEL_A}).json()["reel_id"]
    _analyze(reel, _first_user(), ["Kung Fu Tea"], map_id=personal)
    assert _places_on(client, personal) == ["Kung Fu Tea"]

    second = client.post("/maps", json={"name": "Date nights"}).json()["id"]
    before = len(client.enqueued)

    again = client.post("/reels", json={"url": REEL_A, "map_id": second}).json()
    assert again["place_count"] == 0, "nothing from this reel is on the new map yet"
    assert len(client.enqueued) == before + 1, "the link job must be queued"

    # The worker then copies the cached places across — no re-analysis.
    _analyze(reel, _first_user(), ["Kung Fu Tea"], map_id=second)
    assert _places_on(client, second) == ["Kung Fu Tea"]
    assert _places_on(client, personal) == ["Kung Fu Tea"], "the first map is untouched"


def test_resharing_into_the_same_map_still_does_nothing(client):
    """The dedupe that was working stays working — one venue, one pin per map."""
    personal = client.get("/maps").json()[0]["id"]
    reel = client.post("/reels", json={"url": REEL_A}).json()["reel_id"]
    _analyze(reel, _first_user(), ["Kung Fu Tea"], map_id=personal)
    before = len(client.enqueued)

    again = client.post("/reels", json={"url": REEL_A, "map_id": personal}).json()
    assert again["place_count"] == 1
    assert again["already_analyzed"] is True
    assert len(client.enqueued) == before, "no job for a reel already on this map"
    assert _places_on(client, personal) == ["Kung Fu Tea"]


def test_a_different_reel_about_the_same_place_pins_it_on_the_new_map(client):
    """Two reels, one venue, two maps — each map gets its own pin."""
    personal = client.get("/maps").json()[0]["id"]
    second = client.post("/maps", json={"name": "Date nights"}).json()["id"]

    a = client.post("/reels", json={"url": REEL_A}).json()["reel_id"]
    _analyze(a, _first_user(), ["Kung Fu Tea"], map_id=personal)

    b = client.post("/reels", json={"url": REEL_B, "map_id": second}).json()["reel_id"]
    _analyze(b, _first_user(), ["Kung Fu Tea"], map_id=second)

    assert _places_on(client, personal) == ["Kung Fu Tea"]
    assert _places_on(client, second) == ["Kung Fu Tea"]


def test_a_place_a_friend_already_added_is_not_duplicated(client):
    """Map-scoped, not user-scoped: on a shared map someone else's pin from
    this reel means re-sharing genuinely has nothing to add."""
    trip = client.post("/maps", json={"name": "Trip"}).json()
    code = client.post(f"/maps/{trip['id']}/invite").json()["invite_code"]
    friend = _user("dev:already")
    friend.post(f"/maps/join/{code}")

    reel = friend.post("/reels", json={"url": REEL_A, "map_id": trip["id"]}).json()["reel_id"]
    _analyze(reel, _user_id(friend), ["Kung Fu Tea"], map_id=trip["id"])

    before = len(client.enqueued)
    mine = client.post("/reels", json={"url": REEL_A, "map_id": trip["id"]}).json()
    assert mine["place_count"] == 1
    assert len(client.enqueued) == before, "already on this map, whoever added it"
    assert _places_on(client, trip["id"]) == ["Kung Fu Tea"]
