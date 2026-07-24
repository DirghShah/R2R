"""Instagram reel fetcher (Apify) + an offline stub for local dev."""
from __future__ import annotations

import httpx

from app.config import settings

from .base import (
    ReelData,
    canonical_id,
    collect_handles,
    first_value,
    location_name,
    normalize_hashtags,
)

_APIFY_RUN_SYNC = "https://api.apify.com/v2/acts/{actor}/run-sync-get-dataset-items"


def apify_run(actor: str, payload: dict) -> dict:
    """Run an Apify actor synchronously and return the first dataset item."""
    if not settings.apify_token:
        raise RuntimeError("APIFY_TOKEN is not configured")
    endpoint = _APIFY_RUN_SYNC.format(actor=actor.replace("/", "~"))
    resp = httpx.post(endpoint, params={"token": settings.apify_token}, json=payload, timeout=180)
    resp.raise_for_status()
    items = resp.json()
    if not items:
        raise RuntimeError("Apify returned no data")
    return items[0]


class InstagramFetcher:
    def fetch(self, url: str) -> ReelData:
        item = apify_run(settings.apify_actor,
                         {"directUrls": [url], "resultsType": "details", "resultsLimit": 1})
        caption = first_value(item, "caption", "text", "title")
        return ReelData(
            canonical_id=canonical_id(url),
            url=url,
            platform="instagram",
            caption=caption,
            author_handle=first_value(item, "ownerUsername", "ownerUserName", "username"),
            thumbnail_url=first_value(item, "displayUrl", "imageUrl", "thumbnailUrl"),
            video_url=first_value(item, "videoUrl", "videoUrlHd", "videoUrlBackup"),
            at_handles=collect_handles(item, caption),
            tagged_location=location_name(item),
            tagged_address=(item.get("location") or {}).get("address") if isinstance(item.get("location"), dict) else None,
            hashtags=normalize_hashtags(item.get("hashtags"), caption),
            raw=item,
        )


class StubFetcher:
    """Deterministic sample for local testing (no network, any platform)."""

    SAMPLE = ReelData(
        canonical_id="ig:STUB_NYC_CAFES",
        url="https://www.instagram.com/reel/STUB_NYC_CAFES/",
        platform="instagram",
        caption=(
            "Top 5 cafes in NYC you NEED to try ☕️\n"
            "1. @devocion in Williamsburg — get the cold brew\n"
            "2. @variety_coffee — best croissants\n"
            "3. Stumptown (Ace Hotel) — go early, it gets packed\n"
            "#nyccoffee #williamsburg #nyceats"
        ),
        author_handle="miotravel_",
        video_url=None,  # no video in the stub; extraction runs caption-only
        at_handles=["devocion", "variety_coffee"],
        tagged_location="New York, New York",
        hashtags=["nyccoffee", "williamsburg", "nyceats"],
    )

    def fetch(self, url: str) -> ReelData:
        return self.SAMPLE
