"""Pure-logic tests (no network, no DB, no API keys)."""
import pytest

from worker.fetchers.base import canonical_id, parse_handles, parse_hashtags
from worker.fetchers.instagram import StubFetcher


@pytest.mark.parametrize(
    "url,expected",
    [
        ("https://www.instagram.com/reel/CxYz123_-/", "CxYz123_-"),
        ("https://instagram.com/reels/ABC123/?utm=1", "ABC123"),
        ("https://www.instagram.com/p/DEF456/", "DEF456"),
    ],
)
def test_canonical_id(url, expected):
    assert canonical_id(url) == expected


def test_canonical_id_rejects_non_reel():
    with pytest.raises(ValueError):
        canonical_id("https://example.com/not-a-reel")


def test_parse_handles_dedupes_in_order():
    caption = "love @devocion and @variety_coffee, also @devocion again"
    assert parse_handles(caption) == ["devocion", "variety_coffee"]


def test_parse_hashtags():
    assert parse_hashtags("#nyccoffee #williamsburg") == ["nyccoffee", "williamsburg"]


def test_stub_fetcher_shape():
    data = StubFetcher().fetch("anything")
    assert data.canonical_id == "STUB_NYC_CAFES"
    assert "devocion" in data.at_handles
    assert data.tagged_location == "New York, New York"
