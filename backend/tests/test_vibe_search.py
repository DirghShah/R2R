"""Searching saved places by what they feel like.

Two things this has to get right. Ids that come back from a model must be
checked against the ids that went in, because a model asked for an identifier
will occasionally invent a plausible one. And an empty result has to be a real
answer — a wrong match teaches people the search doesn't work.
"""
from __future__ import annotations

from dataclasses import dataclass

import pytest

# Imported first: it sets DATABASE_URL before any app module binds the engine.
from tests.test_api_flow import REEL_A, _analyze, _first_user, client  # noqa: F401

from app.config import settings  # noqa: E402
from worker import vibe_search  # noqa: E402
from worker.extract import VIBES, normalize_vibe, normalize_vibes  # noqa: E402


# --- the closed list ------------------------------------------------------


@pytest.mark.parametrize("raw,expected", [
    ("cozy", "Cozy"), ("intimate", "Romantic"), ("chill vibes", "Cozy"),
    ("by the water", "Waterfront"), ("skyline", "Great View"),
    ("study spot", "Work-Friendly"), ("hole-in-the-wall", "No-Frills"),
    ("speakeasy", "Hidden Gem"), ("patio", "Outdoor Seating"),
    ("Rooftop", "Rooftop"),
])
def test_one_idea_becomes_one_tag(raw, expected):
    assert normalize_vibe(raw) == expected


def test_a_tag_that_means_nothing_is_dropped_not_kept():
    """There is no Other bucket on purpose: an unrecognised vibe matches nothing
    in a search and would put a dead chip on the map."""
    assert normalize_vibe("weird unknown thing") is None
    assert normalize_vibes(["cozy", "weird unknown thing"]) == ["Cozy"]


def test_tags_are_deduped_and_capped():
    """A place tagged with everything is tagged with nothing, and a model given
    a list will happily use all of it."""
    out = normalize_vibes(["patio", "outdoor", "Rooftop", "Divey", "Quiet", "Brunch"])
    assert out == ["Outdoor Seating", "Rooftop", "Divey", "Quiet"]
    assert len(out) == 4


def test_every_alias_points_at_a_real_tag():
    from worker.extract import _VIBE_ALIASES

    unknown = {v for v in _VIBE_ALIASES.values() if v not in VIBES}
    assert not unknown, f"aliases point at tags that don't exist: {unknown}"


# --- the search itself ----------------------------------------------------


@dataclass
class _Block:
    input: dict
    type: str = "tool_use"
    name: str = "return_matches"


@dataclass
class _Usage:
    input_tokens: int = 100
    output_tokens: int = 20


@dataclass
class _Resp:
    content: list
    usage: _Usage
    stop_reason: str = "tool_use"


def _fake_client(payload: dict):
    class _Messages:
        def create(self, **_kw):
            return _Resp([_Block(payload)], _Usage())

    class _Client:
        messages = _Messages()

    return lambda **_kw: _Client()


PLACES = [
    {"id": "up-1", "name": "Blue Bottle", "vibes": ["Work-Friendly", "Quiet"]},
    {"id": "up-2", "name": "Rooftop 48", "vibes": ["Rooftop", "Great View"]},
]


def test_matches_come_back_ranked(monkeypatch):
    monkeypatch.setattr(vibe_search, "Anthropic", _fake_client(
        {"matches": [{"place_id": "up-2", "reason": "tagged rooftop with a view"},
                     {"place_id": "up-1", "reason": "tagged quiet"}]}))
    out = vibe_search.search("somewhere with a view", PLACES)
    assert [m.place_id for m in out.matches] == ["up-2", "up-1"]
    assert out.matches[0].reason == "tagged rooftop with a view"


def test_an_invented_id_is_thrown_away(monkeypatch):
    """A hallucinated id would surface nothing, or worse, somebody else's place."""
    monkeypatch.setattr(vibe_search, "Anthropic", _fake_client(
        {"matches": [{"place_id": "up-1", "reason": "ok"},
                     {"place_id": "up-999", "reason": "invented"}]}))
    out = vibe_search.search("quiet", PLACES)
    assert [m.place_id for m in out.matches] == ["up-1"]


def test_the_same_place_twice_is_returned_once(monkeypatch):
    monkeypatch.setattr(vibe_search, "Anthropic", _fake_client(
        {"matches": [{"place_id": "up-1", "reason": "a"},
                     {"place_id": "up-1", "reason": "b"}]}))
    assert len(vibe_search.search("quiet", PLACES).matches) == 1


def test_nothing_matching_is_a_real_answer(monkeypatch):
    monkeypatch.setattr(vibe_search, "Anthropic", _fake_client({"matches": []}))
    assert vibe_search.search("a place on the moon", PLACES).matches == []


def test_a_model_that_returns_no_tool_call_does_not_raise(monkeypatch):
    class _Messages:
        def create(self, **_kw):
            return _Resp([], _Usage())

    class _Client:
        messages = _Messages()

    monkeypatch.setattr(vibe_search, "Anthropic", lambda **_kw: _Client())
    assert vibe_search.search("quiet", PLACES).matches == []


def test_an_empty_query_or_no_places_costs_nothing(monkeypatch):
    def _explode(**_kw):
        raise AssertionError("should never reach the model")

    monkeypatch.setattr(vibe_search, "Anthropic", _explode)
    assert vibe_search.search("   ", PLACES).matches == []
    assert vibe_search.search("cozy", []).matches == []


# --- the endpoint ---------------------------------------------------------


def test_search_is_scoped_to_places_you_actually_have(client, monkeypatch):
    reel = client.post("/reels", json={"url": REEL_A}).json()["reel_id"]
    _analyze(reel, _first_user(), ["Kung Fu Tea", "Otto's"])

    seen: dict = {}

    def _capture(query, places):
        seen["query"] = query
        seen["places"] = places
        return vibe_search.VibeSearchResult(
            [vibe_search.VibeMatch(places[0]["id"], "tagged cozy")], 10, 5)

    monkeypatch.setattr(vibe_search, "search", _capture)
    body = client.post("/places/search", json={"query": "somewhere cozy"}).json()

    assert seen["query"] == "somewhere cozy"
    assert {p["name"] for p in seen["places"]} == {"Kung Fu Tea", "Otto's"}
    assert body["considered"] == 2
    assert body["matches"][0]["reason"] == "tagged cozy"


def test_a_search_with_no_saved_places_returns_empty_not_an_error(client, monkeypatch):
    def _explode(*_a, **_kw):
        raise AssertionError("should never reach the model")

    monkeypatch.setattr(vibe_search, "search", _explode)
    body = client.post("/places/search", json={"query": "anything at all"}).json()
    assert body["matches"] == []
    assert body["considered"] == 0


def test_a_failing_search_says_so_rather_than_looking_empty(client, monkeypatch):
    """An error rendered as "no results" tells the person their places are gone."""
    reel = client.post("/reels", json={"url": REEL_A}).json()["reel_id"]
    _analyze(reel, _first_user(), ["Kung Fu Tea"])

    def _boom(*_a, **_kw):
        raise RuntimeError("anthropic down")

    monkeypatch.setattr(vibe_search, "search", _boom)
    assert client.post("/places/search", json={"query": "cozy"}).status_code == 503


def test_a_blank_query_is_refused_before_it_costs_anything(client):
    assert client.post("/places/search", json={"query": "   "}).status_code == 422
    assert client.post("/places/search", json={"query": "a"}).status_code == 422


def test_you_cannot_search_a_map_you_are_not_in(client, monkeypatch):
    from fastapi.testclient import TestClient
    from app.main import app

    stranger = TestClient(app)
    token = stranger.post("/auth/apple", json={"identity_token": "dev:stranger"}).json()
    stranger.headers["Authorization"] = f"Bearer {token['access_token']}"
    mine = client.get("/maps").json()[0]["id"]

    assert stranger.post(
        "/places/search", json={"query": "cozy", "map_id": mine}
    ).status_code in (403, 404)
