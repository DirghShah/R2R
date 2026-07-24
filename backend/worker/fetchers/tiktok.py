"""TikTok fetcher via Apify.

Field names depend on the chosen actor (default: clockworks/tiktok-scraper).
Mapping is defensive; if a real video returns thin data, adjust the keys here or
point APIFY_ACTOR_TIKTOK at a different actor.
"""
from __future__ import annotations

from app.config import settings

from .base import (
    ReelData,
    canonical_id,
    collect_handles,
    first_value,
    normalize_hashtags,
)
from .instagram import apify_run


class TikTokFetcher:
    def fetch(self, url: str) -> ReelData:
        # shouldDownloadVideos=True makes the actor return a real CDN media URL;
        # without it we only get the webVideoUrl (the watch page), which is HTML
        # and can't be frame-sampled.
        item = apify_run(settings.apify_actor_tiktok,
                         {"postURLs": [url], "resultsPerPage": 1, "shouldDownloadVideos": True})
        caption = first_value(item, "text", "caption", "desc", "title")
        author = first_value(item, "authorMeta", "author")
        author_handle = None
        if isinstance(author, dict):
            author_handle = author.get("name") or author.get("uniqueId")
        elif isinstance(author, str):
            author_handle = author

        # Only accept an actual downloadable media URL — never fall back to
        # webVideoUrl (the tiktok.com watch page), which is HTML, not video.
        video_url = None
        media = item.get("mediaUrls")
        if isinstance(media, list) and media:
            video_url = media[0]
        if not video_url:
            video_url = first_value(item, "videoUrl", "downloadAddr")
        meta = item.get("videoMeta")
        if not video_url and isinstance(meta, dict):
            video_url = meta.get("downloadAddr") or meta.get("playAddr")

        # locationMeta carries the exact venue address + name — far stronger than
        # locationCreated ("US"), which is just the country.
        loc = item.get("locationMeta") if isinstance(item.get("locationMeta"), dict) else {}
        tagged_location = loc.get("locationName") or first_value(item, "locationCreated")
        tagged_address = loc.get("address")

        return ReelData(
            canonical_id=canonical_id(url),
            url=url,
            platform="tiktok",
            caption=caption,
            author_handle=author_handle,
            thumbnail_url=first_value(item, "covers", "cover", "thumbnailUrl"),
            video_url=video_url,
            at_handles=_tiktok_handles(item, caption, author_handle),
            tagged_location=tagged_location,
            tagged_address=tagged_address,
            hashtags=normalize_hashtags(item.get("hashtags"), caption),
            raw=item,
        )


def _tiktok_handles(item: dict, caption: str | None, author_handle: str | None) -> list[str]:
    """Prefer the actor's `detailedMentions` (canonical usernames like
    `cafe.luna.nyc`) over the caption regex, which mangles multi-word @tags
    ("@Cafe luna nyc" → "Cafe"). Drop the reel's own author — it's the poster,
    not a place."""
    handles: list[str] = []
    for m in item.get("detailedMentions") or []:
        name = m.get("name") if isinstance(m, dict) else None
        if name and name not in handles:
            handles.append(name)
    for h in collect_handles(item, caption):
        if h not in handles:
            handles.append(h)
    author = (author_handle or "").lstrip("@").lower()
    return [h for h in handles if h.lower() != author]
