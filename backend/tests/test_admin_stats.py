"""The ops view, and the cost column behind it.

Both exist to answer one question without grepping a log stream that rotates:
what is this costing, and is anything stuck.
"""
from __future__ import annotations

import pytest

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


# --- cost breakdown -------------------------------------------------------


def test_the_stats_report_what_is_configured(client, monkeypatch):
    """The first question when a cost looks wrong is which model ran, and the
    code default is the most expensive one — easy to leave unset on a deploy."""
    monkeypatch.setattr(settings, "admin_token", TOKEN)
    monkeypatch.setattr(settings, "anthropic_model", "claude-haiku-4-5")
    cfg = client.get("/admin/stats", headers=_auth(client)).json()["config"]
    assert cfg["claude_model"] == "claude-haiku-4-5"
    assert cfg["geocoder"] == settings.geocoder
    assert cfg["reel_fetcher"] == settings.reel_fetcher


def test_fixed_costs_are_amortised_to_a_month(monkeypatch):
    from app.routers.admin import _fixed_costs

    monkeypatch.setattr(settings, "fixed_costs", (
        '[{"name": "Host", "usd": 5, "period": "monthly"},'
        ' {"name": "Domain", "usd": 24, "period": "annual"},'
        ' {"name": "Laptop", "usd": 2000, "period": "once"}]'
    ))
    f = _fixed_costs()
    assert f["monthly_equivalent"] == 7.0, "annual should be a twelfth per month"
    assert f["annual_equivalent"] == 84.0
    # A one-off spread over an arbitrary window is an invented number, so it is
    # reported separately rather than folded into the monthly figure.
    assert f["one_time_total"] == 2000.0


def test_a_malformed_fixed_cost_override_does_not_break_the_endpoint(client, monkeypatch):
    monkeypatch.setattr(settings, "admin_token", TOKEN)
    monkeypatch.setattr(settings, "fixed_costs", "not json at all")
    body = client.get("/admin/stats", headers=_auth(client)).json()
    assert body["cost_usd"]["fixed"]["items"] == []
    assert body["cost_usd"]["fixed"]["monthly_equivalent"] == 0.0


def test_costs_from_before_the_breakdown_existed_are_not_guessed_at(client, monkeypatch):
    """A vendor split that silently drops old spend reads as a smaller bill than
    the one you actually have."""
    monkeypatch.setattr(settings, "admin_token", TOKEN)

    db = session()
    try:
        db.add(ReelSource(url="https://instagram.com/reel/old", canonical_id="ig:old",
                          status="done", cost_usd=0.25, cost_detail=None))
        db.commit()
    finally:
        db.close()

    vendors = client.get("/admin/stats", headers=_auth(client)).json()
    vendors = vendors["cost_usd"]["by_vendor_all_time"]
    assert vendors["unattributed"] >= 0.25


def test_the_ledger_lists_each_reel_with_its_own_cost(client, monkeypatch):
    monkeypatch.setattr(settings, "admin_token", TOKEN)

    db = session()
    try:
        db.add(ReelSource(
            url="https://instagram.com/reel/led", canonical_id="ig:led", status="done",
            cost_usd=0.0412,
            cost_detail={"model": "claude-haiku-4-5", "places": 3, "input_tokens": 30000,
                         "output_tokens": 400, "claude_usd": 0.032, "fetch_usd": 0.005,
                         "geocode_usd": 0.0042, "total_usd": 0.0412},
        ))
        db.commit()
    finally:
        db.close()

    body = client.get("/admin/reels?limit=200", headers=_auth(client)).json()
    row = next(r for r in body["reels"] if r["cost_usd"] == 0.0412)
    assert row["places"] == 3
    assert row["model"] == "claude-haiku-4-5"
    assert row["input_tokens"] == 30000
    assert row["claude_usd"] + row["fetch_usd"] + row["geocode_usd"] == pytest.approx(0.0412)


def test_the_ledger_is_guarded_by_the_same_token(client, monkeypatch):
    monkeypatch.setattr(settings, "admin_token", TOKEN)
    assert client.get("/admin/reels").status_code == 404
    assert client.get("/admin/reels", headers=_auth(client, "wrong")).status_code == 404
    assert client.get("/admin/reels", headers=_auth(client)).status_code == 200


def test_every_model_we_might_run_has_a_price():
    """A model missing from the table prices at the fallback, which is the most
    expensive entry — deliberately, since a cost report that under-reports is
    the one nobody investigates."""
    from app.config import Settings
    from worker.pipeline import _CLAUDE_PRICES, _claude_cost

    assert Settings(_env_file=None).anthropic_model in _CLAUDE_PRICES, \
        "the default model must be priceable"

    # 1M input tokens on Haiku is $1.00; on an unknown model it must not come
    # back cheaper than that.
    assert _claude_cost("claude-haiku-4-5", 1_000_000, 0) == 1.0
    assert _claude_cost("something-we-have-never-heard-of", 1_000_000, 0) >= 1.0
