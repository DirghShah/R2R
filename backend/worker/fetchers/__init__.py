"""Reel fetchers — swappable behind a common interface, routed by platform.

The fetch step is the most fragile/ToS-sensitive part of the system, so it lives
behind `ReelFetcher`. `REEL_FETCHER=stub` uses the offline sample for any
platform; `REEL_FETCHER=apify` routes to the per-platform Apify fetcher.
"""
from __future__ import annotations

from app.config import settings

from .base import ReelData, ReelFetcher, canonical_id, detect_platform, parse_source
from .instagram import InstagramFetcher, StubFetcher
from .tiktok import TikTokFetcher
from .youtube import YouTubeFetcher

__all__ = [
    "ReelData", "ReelFetcher", "canonical_id", "detect_platform",
    "parse_source", "get_fetcher",
]

_APIFY_FETCHERS = {
    "instagram": InstagramFetcher,
    "tiktok": TikTokFetcher,
    "youtube": YouTubeFetcher,
}


def get_fetcher(platform: str) -> ReelFetcher:
    if settings.reel_fetcher == "stub":
        return StubFetcher()
    if settings.reel_fetcher == "apify":
        cls = _APIFY_FETCHERS.get(platform)
        if cls is None:
            raise ValueError(f"No fetcher for platform {platform!r}")
        return cls()
    raise ValueError(f"Unknown REEL_FETCHER: {settings.reel_fetcher!r}")
