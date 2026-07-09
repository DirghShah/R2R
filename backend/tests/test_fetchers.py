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
