"""Instagram reel fetchers.

ApifyFetcher  — MVP path: hand the URL to an Apify actor and normalize the result.
StubFetcher   — offline/dev path: returns a fixed sample reel so the pipeline and
                extraction can be exercised end-to-end without any vendor or
                network. Useful for the make-or-break CLI test.
"""
from __future__ import annotations

import httpx

from app.config import settings

from .base import ReelData, canonical_id, parse_handles, parse_hashtags

_APIFY_RUN_SYNC = "https://api.apify.com/v2/acts/{actor}/run-sync-get-dataset-items"


class ApifyFetcher:
    def fetch(self, url: str) -> ReelData:
        if not settings.apify_token:
            raise RuntimeError("APIFY_TOKEN is not configured")

        actor = settings.apify_actor.replace("/", "~")
        endpoint = _APIFY_RUN_SYNC.format(actor=actor)
        resp = httpx.post(
            endpoint,
            params={"token": settings.apify_token},
            json={"directUrls": [url], "resultsLimit": 1},
            timeout=120,
        )
        resp.raise_for_status()
        items = resp.json()
        if not items:
            raise RuntimeError(f"Apify returned no data for {url!r}")
        item = items[0]

        caption = item.get("caption") or item.get("text")
        location = item.get("locationName")
        return ReelData(
            canonical_id=canonical_id(url),
            url=url,
            caption=caption,
            author_handle=item.get("ownerUsername"),
            thumbnail_url=item.get("displayUrl"),
            video_url=item.get("videoUrl"),
            at_handles=_collect_handles(item, caption),
            tagged_location=location,
            hashtags=item.get("hashtags") or parse_hashtags(caption),
        )


def _collect_handles(item: dict, caption: str | None) -> list[str]:
    handles = list(parse_handles(caption))
    for tag in item.get("taggedUsers") or []:
        username = tag.get("username") if isinstance(tag, dict) else None
        if username and username not in handles:
            handles.append(username)
    return handles


class StubFetcher:
    """Deterministic sample for local testing (no network)."""

    SAMPLE = ReelData(
        canonical_id="STUB_NYC_CAFES",
        url="https://www.instagram.com/reel/STUB_NYC_CAFES/",
        caption=(
            "Top 5 cafes in NYC you NEED to try ☕️\n"
            "1. @devocion in Williamsburg — get the cold brew\n"
            "2. @variety_coffee — best croissants\n"
            "3. Stumptown (Ace Hotel) — go early, it gets packed\n"
            "#nyccoffee #williamsburg #nyceats"
        ),
        author_handle="miotravel_",
        thumbnail_url=None,
        video_url=None,  # no video in the stub; extraction runs caption-only
        at_handles=["devocion", "variety_coffee"],
        tagged_location="New York, New York",
        hashtags=["nyccoffee", "williamsburg", "nyceats"],
    )

    def fetch(self, url: str) -> ReelData:
        return self.SAMPLE
