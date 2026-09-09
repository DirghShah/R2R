"""Reel fetchers — swappable behind a common interface, routed by platform.

The fetch step is the most fragile part of the system: it depends on platforms
that actively change to break exactly this. So it lives behind `ReelFetcher`,
and — since a single source of truth for something that fragile is a single
point of failure — the default is a *chain*.

  REEL_FETCHER=apify   Apify, falling back to yt-dlp when it fails
  REEL_FETCHER=ytdlp   yt-dlp only
  REEL_FETCHER=stub    the offline sample, for local dev and tests

Apify and yt-dlp are the same category of access; what differs is how they
break. Apify is one vendor's hosted service and actor code; yt-dlp is a local
extractor with thousands of contributors that usually ships a fix within days
of a platform change. When one is down the other often isn't, which is the only
reason to carry both.
"""
from __future__ import annotations

import logging

from app.config import settings

from .base import ReelData, ReelFetcher, canonical_id, detect_platform, parse_source
from .instagram import InstagramFetcher, StubFetcher
from .tiktok import TikTokFetcher
from .ytdlp import YtDlpFetcher
from .youtube import YouTubeFetcher

log = logging.getLogger(__name__)

__all__ = [
    "ReelData", "ReelFetcher", "canonical_id", "detect_platform",
    "parse_source", "get_fetcher", "FallbackFetcher",
]

_APIFY_FETCHERS = {
    "instagram": InstagramFetcher,
    "tiktok": TikTokFetcher,
    "youtube": YouTubeFetcher,
}


class FallbackFetcher:
    """Try each fetcher in order; the first that returns usable data wins.

    "Usable" means a caption or a video URL. A fetcher that returns an empty
    shell counts as a failure — otherwise a silently-degraded scraper would
    look like success and produce reels with nothing to extract from, which is
    worse than an error because nobody investigates it.
    """

    def __init__(self, *fetchers: ReelFetcher) -> None:
        self._fetchers = [f for f in fetchers if f is not None]

    def fetch(self, url: str) -> ReelData:
        errors: list[str] = []
        for fetcher in self._fetchers:
            name = type(fetcher).__name__
            try:
                data = fetcher.fetch(url)
            except Exception as exc:  # noqa: BLE001 — any failure means try the next
                errors.append(f"{name}: {exc}")
                log.warning("fetcher %s failed for %s: %s", name, url, exc)
                continue

            if not (data.caption or data.video_url):
                errors.append(f"{name}: returned no caption and no video")
                log.warning("fetcher %s returned an empty payload for %s", name, url)
                continue

            # Logged on every fetch, not just failures: you want to notice that
            # the primary has been quietly falling back for a week.
            if fetcher is not self._fetchers[0]:
                print(f"[fetch] FALLBACK to {name} for {url} — primary failed: "
                      f"{errors[0] if errors else 'unknown'}", flush=True)
            log.info("fetched %s via %s", url, name)
            return data

        raise RuntimeError("all fetchers failed — " + " | ".join(errors))


def get_fetcher(platform: str) -> ReelFetcher:
    if settings.reel_fetcher == "stub":
        return StubFetcher()

    if settings.reel_fetcher == "ytdlp":
        return YtDlpFetcher()

    if settings.reel_fetcher == "apify":
        cls = _APIFY_FETCHERS.get(platform)
        if cls is None:
            raise ValueError(f"No fetcher for platform {platform!r}")
        if not settings.fetcher_fallback:
            return cls()
        return FallbackFetcher(cls(), YtDlpFetcher())

    raise ValueError(f"Unknown REEL_FETCHER: {settings.reel_fetcher!r}")
