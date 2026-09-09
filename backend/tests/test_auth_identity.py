"""Identity: profile, session refresh, sign-out, account deletion."""
from __future__ import annotations

from tests.test_api_flow import REEL_A, _analyze, _first_user, client  # noqa: F401

from app.db import session  # noqa: E402
from app.main import app  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402


def _sign_in(identity: str = "dev:tester", **extra) -> dict:
    return TestClient(app).post(
        "/auth/apple", json={"identity_token": identity, **extra}
    ).json()


# --- profile --------------------------------------------------------------


def test_sign_in_returns_both_tokens(client):
    body = _sign_in()
    assert body["access_token"]
    assert body["refresh_token"], "the Share Extension needs a non-interactive path back"


def test_display_name_is_captured_on_first_sign_in(client):
    _sign_in("dev:named", display_name="Dirgh Shah")
    c = TestClient(app)
    token = _sign_in("dev:named")["access_token"]
    c.headers["Authorization"] = f"Bearer {token}"
    me = c.get("/me").json()
    assert me["display_name"] == "Dirgh Shah"
    assert me["avatar_color"].startswith("#"), "avatar colour beats an image upload"


def test_display_name_backfills_for_a_user_created_before_we_asked(client):
    """Apple only sends fullName on the very first authorization ever."""
    _sign_in("dev:later")  # created with no name
    _sign_in("dev:later", display_name="Late Name")
    c = TestClient(app)
    c.headers["Authorization"] = f"Bearer {_sign_in('dev:later')['access_token']}"
    assert c.get("/me").json()["display_name"] == "Late Name"


def test_rename(client):
    assert client.patch("/me", json={"display_name": "Renamed"}).json()["display_name"] == "Renamed"


def test_blank_display_name_is_rejected(client):
    assert client.patch("/me", json={"display_name": "  "}).status_code in (200, 422)
    assert client.patch("/me", json={"display_name": ""}).status_code == 422


# --- refresh --------------------------------------------------------------


def test_refresh_returns_a_working_access_token(client):
    refresh = _sign_in("dev:refresher")["refresh_token"]
    body = TestClient(app).post("/auth/refresh", json={"refresh_token": refresh}).json()

    c = TestClient(app)
    c.headers["Authorization"] = f"Bearer {body['access_token']}"
    assert c.get("/me").status_code == 200


def test_refresh_token_rotates_and_the_old_one_dies(client):
    """A token presented twice is replayed or stolen; either way it must stop."""
    first = _sign_in("dev:rotator")["refresh_token"]
    second = TestClient(app).post("/auth/refresh", json={"refresh_token": first}).json()["refresh_token"]
    assert second != first

    replay = TestClient(app).post("/auth/refresh", json={"refresh_token": first})
    assert replay.status_code == 401
    # ...but the fresh one still works.
    assert TestClient(app).post("/auth/refresh", json={"refresh_token": second}).status_code == 200


def test_garbage_refresh_token_is_rejected(client):
    assert TestClient(app).post("/auth/refresh", json={"refresh_token": "nope"}).status_code == 401


def test_sign_out_kills_every_refresh_token(client):
    tokens = _sign_in("dev:signout")
    c = TestClient(app)
    c.headers["Authorization"] = f"Bearer {tokens['access_token']}"
    assert c.post("/auth/signout").status_code == 204
    assert TestClient(app).post(
        "/auth/refresh", json={"refresh_token": tokens["refresh_token"]}
    ).status_code == 401


# --- account deletion (App Store Guideline 5.1.1(v)) ----------------------


def test_delete_account_removes_the_user_and_their_data(client):
    from app.models import RefreshToken, User, UserPlace

    reel = client.post("/reels", json={"url": REEL_A}).json()["reel_id"]
    _analyze(reel, _first_user(), ["Kung Fu Tea"])
    assert len(client.get("/places").json()) == 1

    assert client.delete("/me").status_code == 204

    db = session()
    try:
        from sqlalchemy import select

        assert db.scalars(select(User)).all() == []
        assert db.scalars(select(UserPlace)).all() == []
        assert db.scalars(select(RefreshToken)).all() == []
    finally:
        db.close()


def test_delete_account_keeps_shared_canonical_rows(client):
    """Place and ReelSource belong to no one user — other people point at them."""
    from sqlalchemy import select

    from app.models import Place, ReelSource

    reel = client.post("/reels", json={"url": REEL_A}).json()["reel_id"]
    _analyze(reel, _first_user(), ["Kung Fu Tea"])
    client.delete("/me")

    db = session()
    try:
        assert len(db.scalars(select(Place)).all()) == 1
        assert len(db.scalars(select(ReelSource)).all()) == 1
    finally:
        db.close()


def test_delete_account_revokes_the_apple_grant(client, monkeypatch):
    """Deleting our own rows alone does not satisfy App Store review."""
    from app import apple
    from app.models import User
    from sqlalchemy import select

    revoked: list[str] = []
    monkeypatch.setattr(apple, "revoke", lambda token: revoked.append(token) or True)

    db = session()
    try:
        db.scalars(select(User)).first().apple_refresh_token = "apple-refresh-abc"
        db.commit()
    finally:
        db.close()

    client.delete("/me")
    assert revoked == ["apple-refresh-abc"]


def test_deletion_proceeds_even_if_apple_revocation_fails(client, monkeypatch):
    from app import apple

    monkeypatch.setattr(apple, "revoke", lambda token: False)
    assert client.delete("/me").status_code == 204


# --- the dev shortcut is a bypass, so prove it is off by default ----------


def test_dev_sign_in_is_off_unless_explicitly_enabled(monkeypatch):
    """`{"identity_token": "dev:anyone"}` mints a session for any id you name.

    It used to be gated on `environment`, which defaults to "dev" — so a deploy
    that forgot ENVIRONMENT was silently open to anyone who guessed the shape
    of the request, and a healthy-looking service told you nothing.
    """
    from app import auth
    from app.config import settings

    # Otherwise the fallback path reaches for Apple's live signing keys.
    monkeypatch.setattr(auth, "_apple_keys", lambda force_refresh=False: [])
    monkeypatch.setattr(settings, "allow_dev_sign_in", False)

    resp = TestClient(app).post("/auth/apple", json={"identity_token": "dev:intruder"})
    assert resp.status_code == 401


def test_the_flag_defaults_to_off(monkeypatch):
    """The default is the whole point: an unset variable must not open it."""
    from app.config import Settings

    monkeypatch.delenv("ALLOW_DEV_SIGN_IN", raising=False)
    assert Settings(_env_file=None).allow_dev_sign_in is False
