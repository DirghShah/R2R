"""Maps and invite-link sharing.

Sharing is by link to a specific map — there is no friend graph, so every test
here works with users who have no prior relationship at all.
"""
from __future__ import annotations

# Imported first: it sets DATABASE_URL before any app module binds the engine.
from tests.test_api_flow import REEL_A, REEL_B, _analyze, _first_user, client  # noqa: F401

from fastapi.testclient import TestClient  # noqa: E402

from app.db import session  # noqa: E402
from app.main import app  # noqa: E402


def _user(identity: str) -> TestClient:
    c = TestClient(app)
    token = c.post("/auth/apple", json={
        "identity_token": identity, "display_name": identity.split(":")[-1].title(),
    }).json()["access_token"]
    c.headers["Authorization"] = f"Bearer {token}"
    return c


def _user_id(c: TestClient) -> str:
    return c.get("/me").json()["id"]


# --- the container --------------------------------------------------------


def test_every_user_gets_a_personal_map(client):
    maps = client.get("/maps").json()
    assert len(maps) == 1
    assert maps[0]["is_personal"] is True
    assert maps[0]["is_owner"] is True
    assert maps[0]["member_count"] == 1


def test_places_land_on_the_personal_map_by_default(client):
    """The Share Extension has no map picker, so the default must just work."""
    reel = client.post("/reels", json={"url": REEL_A}).json()["reel_id"]
    _analyze(reel, _first_user(), ["Kung Fu Tea"])

    personal = client.get("/maps").json()[0]
    place = client.get("/places").json()[0]
    assert place["map_id"] == personal["id"]


def test_create_rename_and_delete_a_map(client):
    created = client.post("/maps", json={"name": "NYC Trip", "emoji": "🗽"}).json()
    assert created["name"] == "NYC Trip"
    assert len(client.get("/maps").json()) == 2

    renamed = client.patch(f"/maps/{created['id']}", json={"name": "NYC 2026"}).json()
    assert renamed["name"] == "NYC 2026"

    assert client.delete(f"/maps/{created['id']}").status_code == 204
    assert len(client.get("/maps").json()) == 1


def test_the_personal_map_cannot_be_deleted(client):
    """Shares always need somewhere to land."""
    personal = client.get("/maps").json()[0]
    assert client.delete(f"/maps/{personal['id']}").status_code == 400


def test_the_same_venue_on_two_maps_is_two_pins(client):
    """Dedupe is per map, not per user — the same cafe can be on your personal
    map and a trip map without one suppressing the other."""
    trip = client.post("/maps", json={"name": "Trip"}).json()
    user = _first_user()

    reel_a = client.post("/reels", json={"url": REEL_A}).json()["reel_id"]
    _analyze(reel_a, user, ["Kung Fu Tea"])
    reel_b = client.post("/reels", json={"url": REEL_B}).json()["reel_id"]
    _analyze(reel_b, user, ["Kung Fu Tea"], map_id=trip["id"])

    places = client.get("/places").json()
    assert len(places) == 2
    assert len({p["map_id"] for p in places}) == 2


def test_you_cannot_submit_into_a_map_you_are_not_in(client):
    stranger = _user("dev:stranger")
    theirs = stranger.post("/maps", json={"name": "Private"}).json()
    resp = client.post("/reels", json={"url": REEL_A, "map_id": theirs["id"]})
    assert resp.status_code == 404, "map ids must not be probeable"


# --- sharing by link ------------------------------------------------------


def test_invite_link_lets_a_stranger_join(client):
    """No prior relationship required — that is the whole point of links."""
    trip = client.post("/maps", json={"name": "Dallas Eats"}).json()
    code = client.post(f"/maps/{trip['id']}/invite").json()["invite_code"]

    friend = _user("dev:friend")
    joined = friend.post(f"/maps/join/{code}").json()
    assert joined["id"] == trip["id"]
    assert joined["is_owner"] is False

    assert {m["id"] for m in friend.get("/maps").json()} >= {trip["id"]}
    assert client.get("/maps").json()[1]["member_count"] == 2


def test_preview_works_without_signing_in(client):
    """The join screen has to show what you're joining before asking for auth."""
    trip = client.post("/maps", json={"name": "Dallas Eats", "emoji": "🌮"}).json()
    code = client.post(f"/maps/{trip['id']}/invite").json()["invite_code"]

    anon = TestClient(app)  # deliberately no Authorization header
    preview = anon.get(f"/maps/preview/{code}")
    assert preview.status_code == 200
    assert preview.json()["name"] == "Dallas Eats"
    assert preview.json()["member_count"] == 1


def test_an_invalid_code_says_so(client):
    assert TestClient(app).get("/maps/preview/NOPENOPE").status_code == 404


def test_rotating_the_code_kills_old_links(client):
    trip = client.post("/maps", json={"name": "Trip"}).json()
    old = client.post(f"/maps/{trip['id']}/invite").json()["invite_code"]
    new = client.post(f"/maps/{trip['id']}/invite?rotate=true").json()["invite_code"]
    assert new != old
    assert _user("dev:late").post(f"/maps/join/{old}").status_code == 404
    assert _user("dev:ontime").post(f"/maps/join/{new}").status_code == 200


def test_joining_twice_is_harmless(client):
    trip = client.post("/maps", json={"name": "Trip"}).json()
    code = client.post(f"/maps/{trip['id']}/invite").json()["invite_code"]
    friend = _user("dev:twice")
    friend.post(f"/maps/join/{code}")
    friend.post(f"/maps/join/{code}")
    assert client.get(f"/maps/{trip['id']}/members").json().__len__() == 2


def test_a_member_can_rename_a_shared_map_not_just_the_owner(client):
    """The name is part of the map's content, like its places — not a
    structural decision like who can invite or delete it."""
    trip = client.post("/maps", json={"name": "Dallas Eats"}).json()
    code = client.post(f"/maps/{trip['id']}/invite").json()["invite_code"]
    friend = _user("dev:renamer")
    friend.post(f"/maps/join/{code}")

    renamed = friend.patch(f"/maps/{trip['id']}", json={"name": "Dallas Trip 2026"})
    assert renamed.status_code == 200
    assert renamed.json()["name"] == "Dallas Trip 2026"
    # The owner sees the rename too — it's one shared row, not per-member state.
    assert client.get("/maps").json()[1]["name"] == "Dallas Trip 2026"


def test_the_personal_map_can_be_renamed_even_though_it_cannot_be_deleted(client):
    """"My Map" is a default name, not a fixed identity — and it's often the
    first map people share, so it's the one they most want to rename."""
    personal = client.get("/maps").json()[0]
    assert personal["is_personal"] is True

    renamed = client.patch(f"/maps/{personal['id']}", json={"name": "Dallas"})
    assert renamed.status_code == 200
    assert renamed.json()["name"] == "Dallas"
    # Still undeletable — renaming and deleting are different permissions.
    assert client.delete(f"/maps/{personal['id']}").status_code == 400


def test_only_the_owner_can_mint_an_invite(client):
    trip = client.post("/maps", json={"name": "Trip"}).json()
    code = client.post(f"/maps/{trip['id']}/invite").json()["invite_code"]
    friend = _user("dev:member")
    friend.post(f"/maps/join/{code}")
    assert friend.post(f"/maps/{trip['id']}/invite").status_code == 403


def test_invite_code_is_only_returned_to_the_owner(client):
    trip = client.post("/maps", json={"name": "Trip"}).json()
    client.post(f"/maps/{trip['id']}/invite")
    friend = _user("dev:nosy")
    code = client.post(f"/maps/{trip['id']}/invite").json()["invite_code"]
    friend.post(f"/maps/join/{code}")

    theirs = next(m for m in friend.get("/maps").json() if m["id"] == trip["id"])
    assert theirs["invite_code"] is None


# --- collaboration --------------------------------------------------------


def test_both_members_see_each_others_pins_with_attribution(client):
    trip = client.post("/maps", json={"name": "Shared"}).json()
    code = client.post(f"/maps/{trip['id']}/invite").json()["invite_code"]
    friend = _user("dev:priya")
    friend.post(f"/maps/join/{code}")

    reel = friend.post("/reels", json={"url": REEL_B, "map_id": trip["id"]}).json()["reel_id"]
    _analyze(reel, _user_id(friend), ["Kung Fu Tea"], map_id=trip["id"])

    for who in (client, friend):
        shared = [p for p in who.get("/places").json() if p["map_id"] == trip["id"]]
        assert len(shared) == 1
        assert shared[0]["added_by_name"] == "Priya", "attribution is the payoff of sharing"
        assert shared[0]["added_by_color"].startswith("#")


def test_a_member_can_delete_a_pin_someone_else_added(client):
    """Shared maps need shared cleanup, or wrong pins are stuck forever."""
    trip = client.post("/maps", json={"name": "Shared"}).json()
    code = client.post(f"/maps/{trip['id']}/invite").json()["invite_code"]
    friend = _user("dev:cleaner")
    friend.post(f"/maps/join/{code}")

    reel = client.post("/reels", json={"url": REEL_A, "map_id": trip["id"]}).json()["reel_id"]
    _analyze(reel, _first_user(), ["Kung Fu Tea"], map_id=trip["id"])

    pin = [p for p in friend.get("/places").json() if p["map_id"] == trip["id"]][0]
    assert friend.delete(f"/places/{pin['id']}").status_code == 204


def test_leaving_a_map_removes_access_but_keeps_it_for_everyone_else(client):
    trip = client.post("/maps", json={"name": "Shared"}).json()
    code = client.post(f"/maps/{trip['id']}/invite").json()["invite_code"]
    friend = _user("dev:leaver")
    friend.post(f"/maps/join/{code}")

    reel = client.post("/reels", json={"url": REEL_A, "map_id": trip["id"]}).json()["reel_id"]
    _analyze(reel, _first_user(), ["Kung Fu Tea"], map_id=trip["id"])
    assert any(p["map_id"] == trip["id"] for p in friend.get("/places").json())

    assert friend.delete(f"/maps/{trip['id']}").status_code == 204
    assert not any(p["map_id"] == trip["id"] for p in friend.get("/places").json())
    # The owner still has it.
    assert any(p["map_id"] == trip["id"] for p in client.get("/places").json())


def test_owner_can_remove_a_member_but_a_member_cannot_remove_others(client):
    trip = client.post("/maps", json={"name": "Shared"}).json()
    code = client.post(f"/maps/{trip['id']}/invite").json()["invite_code"]
    a, b = _user("dev:mem_a"), _user("dev:mem_b")
    a.post(f"/maps/join/{code}")
    b.post(f"/maps/join/{code}")

    assert a.delete(f"/maps/{trip['id']}/members/{_user_id(b)}").status_code == 403
    assert client.delete(f"/maps/{trip['id']}/members/{_user_id(b)}").status_code == 204
    assert len(client.get(f"/maps/{trip['id']}/members").json()) == 2


def test_the_owner_cannot_be_removed(client):
    trip = client.post("/maps", json={"name": "Shared"}).json()
    owner_id = _user_id(client)
    assert client.delete(f"/maps/{trip['id']}/members/{owner_id}").status_code == 400


def test_non_members_cannot_read_a_maps_members(client):
    trip = client.post("/maps", json={"name": "Private"}).json()
    assert _user("dev:outsider").get(f"/maps/{trip['id']}/members").status_code == 404


# --- live updates (push, not websockets) ----------------------------------


def test_adding_to_a_shared_map_notifies_the_other_members(client, monkeypatch):
    """The 'live' in live updates — no websocket, just a push and a refresh."""
    from worker import pipeline

    trip = client.post("/maps", json={"name": "Shared"}).json()
    code = client.post(f"/maps/{trip['id']}/invite").json()["invite_code"]
    friend = _user("dev:notify_me")
    friend.post(f"/maps/join/{code}")

    sent: list[tuple[str, str]] = []
    monkeypatch.setattr(pipeline.push, "notify_user",
                        lambda uid, **kw: sent.append((uid, kw["body"])))

    db = session()
    try:
        pipeline._notify_other_members(db, trip["id"], _user_id(client), 3)
    finally:
        db.close()

    assert len(sent) == 1, "only the other member should be notified"
    assert sent[0][0] == _user_id(friend)
    assert "3 places" in sent[0][1]


def test_a_personal_map_notifies_nobody_else(client, monkeypatch):
    from worker import pipeline

    sent: list = []
    monkeypatch.setattr(pipeline.push, "notify_user", lambda uid, **kw: sent.append(uid))
    personal = client.get("/maps").json()[0]

    db = session()
    try:
        pipeline._notify_other_members(db, personal["id"], _user_id(client), 2)
    finally:
        db.close()
    assert sent == []


# --- universal links ------------------------------------------------------


def test_apple_app_site_association_is_served_for_universal_links(client, monkeypatch):
    """iOS ignores this file silently if it isn't JSON at exactly this path,
    and every invite link then opens Safari instead of the app."""
    from app.routers import links

    monkeypatch.setattr(links.settings, "apple_team_id", "98B96Q5HQP")
    resp = TestClient(app).get("/.well-known/apple-app-site-association")
    assert resp.status_code == 200
    assert resp.headers["content-type"].startswith("application/json")
    details = resp.json()["applinks"]["details"][0]
    assert details["paths"] == ["/join/*"]
    assert details["appID"].startswith("98B96Q5HQP."), "the real team id must be in the appID"


def test_association_file_refuses_to_serve_without_a_team_id(client, monkeypatch):
    """A placeholder appID is worse than none: iOS caches the mismatch and every
    invite link opens Safari permanently, with nothing to explain why."""
    from app.routers import links

    monkeypatch.setattr(links.settings, "apple_team_id", None)
    resp = TestClient(app).get("/.well-known/apple-app-site-association")
    assert resp.status_code == 503
    assert "APPLE_TEAM_ID" in resp.json()["error"]


def test_invite_link_has_a_web_fallback_for_people_without_the_app(client):
    """The whole growth loop depends on the link working before install."""
    trip = client.post("/maps", json={"name": "Dallas Eats", "emoji": "🌮"}).json()
    invite = client.post(f"/maps/{trip['id']}/invite").json()
    assert invite["invite_url"].endswith(f"/join/{invite['invite_code']}")

    page = TestClient(app).get(f"/join/{invite['invite_code']}")
    assert page.status_code == 200
    assert "Dallas Eats" in page.text


def test_a_dead_invite_link_renders_a_real_page_not_a_stack_trace(client):
    page = TestClient(app).get("/join/DEADLINK")
    assert page.status_code == 404
    assert "no longer valid" in page.text


# --- account deletion with shared maps ------------------------------------


def test_deleting_an_account_keeps_its_pins_on_other_peoples_maps(client):
    """A pin added to a shared map belongs to that map, not to whoever added
    it — deleting your account must not silently gut your friends' maps."""
    trip = client.post("/maps", json={"name": "Shared"}).json()
    code = client.post(f"/maps/{trip['id']}/invite").json()["invite_code"]
    friend = _user("dev:departing")
    friend.post(f"/maps/join/{code}")

    reel = friend.post("/reels", json={"url": REEL_B, "map_id": trip["id"]}).json()["reel_id"]
    _analyze(reel, _user_id(friend), ["Kung Fu Tea"], map_id=trip["id"])
    assert len([p for p in client.get("/places").json() if p["map_id"] == trip["id"]]) == 1

    assert friend.delete("/me").status_code == 204

    # The pin survives, re-attributed to the map owner rather than dangling.
    remaining = [p for p in client.get("/places").json() if p["map_id"] == trip["id"]]
    assert len(remaining) == 1, "the departing member's pin was lost"
    assert remaining[0]["added_by_id"] == _user_id(client)
    assert len(client.get(f"/maps/{trip['id']}/members").json()) == 1


def test_deleting_an_owner_removes_the_shared_map_for_everyone(client):
    """The alternative — a map with no owner — is worse than losing it."""
    trip = client.post("/maps", json={"name": "Doomed"}).json()
    code = client.post(f"/maps/{trip['id']}/invite").json()["invite_code"]
    friend = _user("dev:survivor")
    friend.post(f"/maps/join/{code}")
    assert any(m["id"] == trip["id"] for m in friend.get("/maps").json())

    assert client.delete("/me").status_code == 204

    assert not any(m["id"] == trip["id"] for m in friend.get("/maps").json())
    # ...and the survivor still has their own personal map.
    assert len(friend.get("/maps").json()) == 1


# --- input the app would never send ---------------------------------------


def test_a_name_of_only_spaces_is_refused(client):
    """min_length=1 accepts "   ", which the handler then strips to "".

    The app trims before sending, so this only matters for anything that isn't
    the app — but a shared map any member can rename to nothing is worth one
    validator. An unnamed row in the switcher is unidentifiable and unsearchable.
    """
    assert client.post("/maps", json={"name": "   "}).status_code == 422

    trip = client.post("/maps", json={"name": "Trip"}).json()
    assert client.patch(f"/maps/{trip['id']}", json={"name": "\t \n"}).status_code == 422
    assert client.get("/maps").json(), "the map survived the rejected rename"
    assert next(m for m in client.get("/maps").json() if m["id"] == trip["id"])["name"] == "Trip"

    assert client.patch("/me", json={"display_name": " "}).status_code == 422


def test_surrounding_whitespace_is_trimmed_rather_than_rejected(client):
    created = client.post("/maps", json={"name": "  Lisbon  "}).json()
    assert created["name"] == "Lisbon"
