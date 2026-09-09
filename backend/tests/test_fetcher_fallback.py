"""The second fetch path.

Reel fetching depends on platforms that actively change to break it, and a
single source for something that fragile is a single point of failure. Apify
and yt-dlp fail differently — a hosted service versus a local extractor — so
carrying both means one outage isn't an outage.
"""
from __future__ import annotations

# Imported first: it sets DATABASE_URL before any app module binds the engine.
from tests.test_api_flow import client  # noqa: F401

import pytest  # noqa: E402

from app.config import settings  # noqa: E402
from worker.fetchers import FallbackFetcher, get_fetcher  # noqa: E402
from worker.fetchers.base import ReelData  # noqa: E402

URL = "https://www.instagram.com/reel/AAAAAAAAAAA/"


class _Ok:
    def __init__(self, caption="a caption"):
        self.caption = caption
        self.calls = 0

    def fetch(self, url):
        self.calls += 1
        return ReelData(canonical_id="ig:X", url=url, caption=self.caption)


class _Broken:
    def __init__(self):
        self.calls = 0

    def fetch(self, url):
        self.calls += 1
        raise RuntimeError("actor timed out")


class _Empty:
    """The dangerous case: a scraper that 'succeeds' but returns nothing."""

    def __init__(self):
        self.calls = 0

    def fetch(self, url):
        self.calls += 1
        return ReelData(canonical_id="ig:X", url=url)


def test_the_primary_is_used_when_it_works():
    primary, secondary = _Ok(), _Ok()
    data = FallbackFetcher(primary, secondary).fetch(URL)
    assert data.caption == "a caption"
    assert primary.calls == 1
    assert secondary.calls == 0, "the fallback must not run when the primary succeeded"


def test_a_raising_primary_falls_through():
    primary, secondary = _Broken(), _Ok("from yt-dlp")
    assert FallbackFetcher(primary, secondary).fetch(URL).caption == "from yt-dlp"
    assert primary.calls == 1 and secondary.calls == 1


def test_an_empty_payload_counts_as_a_failure():
    """A degraded scraper that returns an empty shell looks like success and
    produces reels with nothing to extract from — worse than an error, because
    nobody investigates it."""
    primary, secondary = _Empty(), _Ok("from yt-dlp")
    assert FallbackFetcher(primary, secondary).fetch(URL).caption == "from yt-dlp"
    assert primary.calls == 1 and secondary.calls == 1


def test_when_everything_fails_the_error_names_both():
    with pytest.raises(RuntimeError) as exc:
        FallbackFetcher(_Broken(), _Broken()).fetch(URL)
    assert exc.value.args[0].count("actor timed out") == 2, "both failures must be reported"


def test_apify_is_chained_with_ytdlp_by_default(monkeypatch):
    monkeypatch.setattr(settings, "reel_fetcher", "apify")
    monkeypatch.setattr(settings, "fetcher_fallback", True)
    chain = get_fetcher("instagram")
    assert [type(f).__name__ for f in chain._fetchers] == ["InstagramFetcher", "YtDlpFetcher"]


def test_the_fallback_can_be_turned_off(monkeypatch):
    monkeypatch.setattr(settings, "reel_fetcher", "apify")
    monkeypatch.setattr(settings, "fetcher_fallback", False)
    assert type(get_fetcher("instagram")).__name__ == "InstagramFetcher"


def test_ytdlp_can_be_the_only_fetcher(monkeypatch):
    monkeypatch.setattr(settings, "reel_fetcher", "ytdlp")
    assert type(get_fetcher("instagram")).__name__ == "YtDlpFetcher"


def test_the_stub_is_never_chained(monkeypatch):
    """Tests and local dev must stay offline — a fallback that reached the
    network would make the suite depend on Instagram being up."""
    monkeypatch.setattr(settings, "reel_fetcher", "stub")
    assert type(get_fetcher("instagram")).__name__ == "StubFetcher"
