"""The ops view, and the cost column behind it.

Both exist to answer one question without grepping a log stream that rotates:
what is this costing, and is anything stuck.
"""
from __future__ import annotations

# Imported first: it sets DATABASE_URL before any app module binds the engine.
from tests.test_api_flow import REEL_A, REEL_B, _analyze, _first_user, client  # noqa: F401

from app.config import settings  # noqa: E402
from app.db import session  # noqa: E402
from app.models import ReelSource  # noqa: E402

TOKEN = "test-admin-token"


def _auth(c, token=TOKEN):
    return {"Authorization": f"Bearer {token}"}


def test_stats_are_hidden_when_no_token_is_configured(client, monkeypatch):
    """404, not 401 — an endpoint that says 'unauthorized' has confirmed it exists."""
    monkeypatch.setattr(settings, "admin_token", None)
    assert client.get("/admin/stats").status_code == 404
    assert client.get("/admin/stats", headers=_auth(client)).status_code == 404


def test_a_wrong_token_also_gets_404(client, monkeypatch):
    monkeypatch.setattr(settings, "admin_token", TOKEN)
    assert client.get("/admin/stats", headers=_auth(client, "nope")).status_code == 404
    assert client.get("/admin/stats").status_code == 404


def test_stats_report_users_reels_places_and_cost(client, monkeypatch):
    monkeypatch.setattr(settings, "admin_token", TOKEN)
    reel = client.post("/reels", json={"url": REEL_A}).json()["reel_id"]
    _analyze(reel, _first_user(), ["Kung Fu Tea", "Otto's"])

    body = client.get("/admin/stats", headers=_auth(client)).json()
    assert body["users"]["total"] >= 1
    assert body["reels"]["total"] >= 1
    assert body["places"]["saved"] == 2
    assert body["places"]["maps"] >= 1
    assert "all_time" in body["cost_usd"]


def test_cost_is_summed_from_the_stored_column(client, monkeypatch):
    monkeypatch.setattr(settings, "admin_token", TOKEN)
    a = client.post("/reels", json={"url": REEL_A}).json()["reel_id"]
    b = client.post("/reels", json={"url": REEL_B}).json()["reel_id"]

    db = session()
    try:
        db.get(ReelSource, a).cost_usd = 0.27
        db.get(ReelSource, b).cost_usd = 0.03
        db.commit()
    finally:
        db.close()

    cost = client.get("/admin/stats", headers=_auth(client)).json()["cost_usd"]
    assert cost["all_time"] == 0.30
    assert cost["avg_per_reel_30d"] == 0.15


def test_reels_with_no_recorded_cost_do_not_count_as_zero(client, monkeypatch):
    """Reels analysed before the column existed have an unknown cost. Treating
    that as $0 would understate every historical total."""
    monkeypatch.setattr(settings, "admin_token", TOKEN)
    a = client.post("/reels", json={"url": REEL_A}).json()["reel_id"]
    client.post("/reels", json={"url": REEL_B})  # left with cost_usd = None

    db = session()
    try:
        db.get(ReelSource, a).cost_usd = 0.20
        db.commit()
    finally:
        db.close()

    assert client.get("/admin/stats", headers=_auth(client)).json()["cost_usd"]["all_time"] == 0.20


def test_a_stuck_reel_is_surfaced(client, monkeypatch):
    """The signal that the worker died mid-job. Anything above zero here needs
    looking at, and it's invisible from the outside otherwise."""
    from datetime import datetime, timedelta, timezone

    monkeypatch.setattr(settings, "admin_token", TOKEN)
    reel_id = client.post("/reels", json={"url": REEL_A}).json()["reel_id"]

    db = session()
    try:
        reel = db.get(ReelSource, reel_id)
        reel.status = "processing"
        reel.started_at = datetime.now(timezone.utc) - timedelta(hours=2)
        db.commit()
    finally:
        db.close()

    assert client.get("/admin/stats", headers=_auth(client)).json()["reels"]["stuck"] == 1
