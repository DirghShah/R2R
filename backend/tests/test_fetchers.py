"""Pure-logic tests (no network, no DB, no API keys)."""
import pytest

from worker.fetchers.base import (
    canonical_id,
    normalize_hashtags,
    parse_handles,
    parse_hashtags,
    parse_source,
)
from worker.fetchers.instagram import StubFetcher


@pytest.mark.parametrize(
    "url,platform,cid",
    [
        ("https://www.instagram.com/reel/CxYz123_-/", "instagram", "ig:CxYz123_-"),
        ("https://instagram.com/reels/ABC123/?utm=1", "instagram", "ig:ABC123"),
        ("https://www.instagram.com/p/DEF456/", "instagram", "ig:DEF456"),
        ("https://www.tiktok.com/@user.name/video/7412345678901234567",
         "tiktok", "tt:7412345678901234567"),
        ("https://vm.tiktok.com/ZMabc123/", "tiktok", "tt:ZMabc123"),
        ("https://www.youtube.com/shorts/abc-DEF_12", "youtube", "yt:abc-DEF_12"),
        ("https://youtu.be/xyz789", "youtube", "yt:xyz789"),
        ("https://www.youtube.com/watch?v=Ghijk12", "youtube", "yt:Ghijk12"),
    ],
)
def test_parse_source(url, platform, cid):
    assert parse_source(url) == (platform, cid)
    assert canonical_id(url) == cid


def test_parse_source_rejects_unknown():
    with pytest.raises(ValueError):
        parse_source("https://example.com/not-a-reel")


def test_parse_handles_dedupes_in_order():
    caption = "love @devocion and @variety_coffee, also @devocion again"
    assert parse_handles(caption) == ["devocion", "variety_coffee"]


def test_parse_hashtags():
    assert parse_hashtags("#nyccoffee #williamsburg") == ["nyccoffee", "williamsburg"]


def test_normalize_hashtags_handles_dict_and_str():
    assert normalize_hashtags(["a", {"name": "b"}, {"nope": 1}], None) == ["a", "b"]
    assert normalize_hashtags(None, "#c #d") == ["c", "d"]


def test_stub_fetcher_shape():
    data = StubFetcher().fetch("anything")
    assert data.canonical_id == "ig:STUB_NYC_CAFES"
    assert data.platform == "instagram"
    assert "devocion" in data.at_handles


def test_geocode_name_verification():
    from worker import geocode

    class P:
        name = "Devoción"
        instagram_handle = "devocion"
        city = "New York"
        neighborhood = None

    p = P()
    assert geocode._result_names_venue(p, "Devocion, 69 Grand St, Brooklyn, New York")
    # City-centroid style result must be rejected (wrong-pin protection)
    assert not geocode._result_names_venue(p, "New York, United States")


def test_extraction_schema_has_country_fields():
    from worker.extract import ExtractedPlace, ReelExtraction

    assert "country" in ExtractedPlace.model_fields
    assert "primary_country" in ReelExtraction.model_fields


@pytest.mark.parametrize(
    "address,expected",
    [
        ("133 Duane St, New York, NY 10013, USA", "NY"),
        ("1023 E Trinity Mills Rd, Carrollton, TX 75006, USA", "TX"),
        ("100 Queen St W, Toronto, ON M5H 2N2, Canada", "ON"),
        ("Dallas, TX", "TX"),
        # International formats must yield nothing rather than a wrong label.
        ("5 Rue de Rivoli, 75001 Paris, France", None),
        ("Shibuya City, Tokyo 150-0002, Japan", None),
        ("Somewhere", None),
        (None, None),
    ],
)
def test_region_from_address(address, expected):
    from worker.geocode import region_from_address

    assert region_from_address(address) == expected


def test_region_from_google_components():
    from worker.geocode import _region_from_components

    components = [
        {"longText": "New York", "shortText": "New York", "types": ["locality"]},
        {"longText": "New York", "shortText": "NY", "types": ["administrative_area_level_1"]},
    ]
    assert _region_from_components(components) == "NY"
    assert _region_from_components(None) is None


def test_region_from_osm_prefers_iso_subdivision():
    from worker.geocode import _region_from_osm

    assert _region_from_osm({"address": {"state": "Texas", "ISO3166-2-lvl4": "US-TX"}}) == "TX"
    # No ISO code and a verbose state name -> no label (better than "Texas, TX")
    assert _region_from_osm({"address": {"state": "Bavaria"}}) is None


def test_notify_messages_cover_every_outcome(monkeypatch):
    """A user who shared a reel and walked away must hear back either way."""
    from worker import pipeline

    sent = []
    monkeypatch.setattr(pipeline.push, "notify_user",
                        lambda user_id, **kw: sent.append(kw))

    class Reel:
        id = "r1"
        status = "done"

    reel = Reel()
    pipeline._notify("u1", 3, reel)
    assert "3 places" in sent[-1]["body"]

    pipeline._notify("u1", 1, reel)
    assert "1 place saved" in sent[-1]["body"], "should not say '1 places'"

    pipeline._notify("u1", 0, reel)
    assert "No places" in sent[-1]["title"]

    reel.status = "failed"
    pipeline._notify("u1", 0, reel)
    assert "Couldn't analyze" in sent[-1]["title"]

    assert all(kw["deep_link"] == "reelmap://reels/r1" for kw in sent)


def test_push_is_a_noop_without_apns_credentials(monkeypatch):
    """Local dev has no APNs key; that must not raise into the analysis job."""
    from worker import push

    monkeypatch.setattr(push.settings, "apns_key_path", None)
    push.notify_user("u1", title="t", body="b")  # must not raise
