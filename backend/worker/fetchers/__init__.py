"""Reel fetchers — swappable behind a common interface.

The fetch step is the most fragile/ToS-sensitive part of the system, so it lives
behind `ReelFetcher` and is selected by config (`REEL_FETCHER`). MVP ships with
the Apify vendor fetcher; a yt-dlp fetcher can be dropped in later without
touching the pipeline.
"""
from __future__ import annotations

from app.config import settings

from .base import ReelData, ReelFetcher, canonical_id
from .instagram import ApifyFetcher, StubFetcher

__all__ = ["ReelData", "ReelFetcher", "canonical_id", "get_fetcher"]


def get_fetcher() -> ReelFetcher:
    name = settings.reel_fetcher
    if name == "apify":
        return ApifyFetcher()
    if name == "stub":
        return StubFetcher()
    raise ValueError(f"Unknown REEL_FETCHER: {name!r}")
