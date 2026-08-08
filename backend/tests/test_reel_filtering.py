"""Only reels about visitable food-and-drink venues get pinned.

The money argument: Google Places is ~90% of the marginal cost of a reel, so
every rejection here has to happen *after* the (cheap) Claude call and *before*
any geocoding. These tests assert that ordering, not just the end state — a
version that rejected correctly but still geocoded first would pass a
places-count assertion while quietly costing the same as before.
"""
from __future__ import annotations

# Imported first: it sets DATABASE_URL before any app module binds the engine.
from tests.test_api_flow import REEL_A, _first_user, client  # noqa: F401

import pytest  # noqa: E402

from app.config import settings  # noqa: E402
from app.db import session  # noqa: E402
from app.models import ReelSource  # noqa: E402
from worker import pipeline  # noqa: E402
from worker.extract import ExtractedPlace, ExtractionResult, ReelExtraction  # noqa: E402
from worker.fetchers.base import ReelData  # noqa: E402


def _place(name: str, category: str = "cafe") -> ExtractedPlace:
    return ExtractedPlace(
        name=name, category=category, description="d", confidence=0.9, city="Dallas",
    )


@pytest.fixture
def run(client, monkeypatch):  # noqa: F811
    """Drive the real analyse path with the network stages stubbed.

    Returns a callable taking the extractor's verdict and giving back the
    reel row plus a record of how many times geocoding was reached.
    """
    geocoded: list[str] = []

    monkeypatch.setattr(pipeline, "get_fetcher", lambda _p: type(
        "F", (), {"fetch": staticmethod(lambda url: ReelData(canonical_id="c", url=url))},
    ))
    monkeypatch.setattr(pipeline.frames, "sample_frames", lambda *a, **k: [])
    monkeypatch.setattr(pipeline.push, "notify_user", lambda *a, **k: None)

    def _geocode(ep, address_hint=None):
        geocoded.append(ep.name)
        return pipeline.geocode.GeocodeResult(
            name=ep.name, lat=32.7, lng=-96.8, city="Dallas", country="USA",
            external_place_id=f"gp:{ep.name.lower()}",
        )

    monkeypatch.setattr(pipeline.geocode, "geocode", _geocode)

    def _run(kind: str, places: list[ExtractedPlace]):
        monkeypatch.setattr(pipeline.extract, "extract_places", lambda **kw: ExtractionResult(
            extraction=ReelExtraction(reel_kind=kind, places=places, overall_summary="s"),
            input_tokens=10, output_tokens=10,
        ))
        reel_id = client.post("/reels", json={"url": REEL_A}).json()["reel_id"]
        result = pipeline.analyze_reel(reel_id, _first_user())
        db = session()
        try:
            return result, db.get(ReelSource, reel_id), geocoded
        finally:
            db.close()

    return _run


@pytest.mark.parametrize("kind", ["advertisement", "recipe_or_cooking",
                                  "product_or_service", "not_places"])
def test_non_venue_reels_are_rejected_before_any_geocoding(run, kind):
    """A CookUnity ad must not cost a single Google Places call."""
    result, reel, geocoded = run(kind, [_place("CookUnity")])

    assert result["status"] == "unsupported"
    assert reel.status == "unsupported"
    assert geocoded == [], "rejected reels must not reach the geocoder — that's the cost"


def test_the_rejection_reason_is_written_for_the_user(run):
    _, reel, _ = run("advertisement", [])
    assert "ad" in reel.error.lower()
    # No stack traces, no exception class names, no jargon leaking to the phone.
    assert "Error" not in reel.error and "Exception" not in reel.error


def test_a_genuine_venue_reel_still_analyses(run):
    result, reel, geocoded = run("venue_recommendation",
                                 [_place("Otto's Coffee"), _place("Tacos y Más", "restaurant")])
    assert result["status"] == "done"
    assert reel.status == "done"
    assert sorted(geocoded) == ["Otto's Coffee", "Tacos y Más"]


def test_places_outside_the_allowed_categories_are_dropped_not_geocoded(run):
    """One hotel in a "best of Dallas" reel shouldn't cost a Places lookup..."""
    result, _, geocoded = run("venue_recommendation", [
        _place("Otto's Coffee"),
        _place("The Joule", "hotel"),
        _place("Reunion Tower", "sight"),
    ])
    assert result["status"] == "done"
    assert geocoded == ["Otto's Coffee"]


def test_a_reel_of_only_disallowed_places_is_rejected(run):
    result, reel, geocoded = run("venue_recommendation", [_place("Reunion Tower", "sight")])
    assert reel.status == "unsupported"
    assert geocoded == []
    assert "caf" in reel.error.lower() or "restaurant" in reel.error.lower()


def test_widening_the_category_list_needs_no_code_change(run, monkeypatch):
    """The food-only scope is a setting, so an app that later wants hotels
    flips one value rather than editing the pipeline."""
    monkeypatch.setattr(settings, "allowed_place_categories", "cafe,restaurant,bar,hotel")
    result, _, geocoded = run("venue_recommendation", [_place("The Joule", "hotel")])
    assert result["status"] == "done"
    assert geocoded == ["The Joule"]


def test_resharing_a_rejected_reel_is_free(run, client):  # noqa: F811
    """Re-analysing would pay a fetch and a Claude call to reach the same
    verdict, so the stored one is served instead."""
    run("advertisement", [_place("CookUnity")])
    before = len(client.enqueued)

    again = client.post("/reels", json={"url": REEL_A}).json()
    assert again["status"] == "unsupported"
    assert again["already_analyzed"] is True
    assert again["error"], "the app needs the reason to show, not just a status"
    assert len(client.enqueued) == before, "a rejected reel must never be re-queued"
