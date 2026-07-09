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
        item = apify_run(settings.apify_actor_tiktok,
                         {"postURLs": [url], "resultsPerPage": 1, "shouldDownloadVideos": False})
        caption = first_value(item, "text", "caption", "desc", "title")
        author = first_value(item, "authorMeta", "author")
        author_handle = None
        if isinstance(author, dict):
            author_handle = author.get("name") or author.get("uniqueId")
        elif isinstance(author, str):
            author_handle = author

        video_url = first_value(item, "videoUrl", "downloadAddr", "webVideoUrl")
        meta = item.get("videoMeta")
        if not video_url and isinstance(meta, dict):
            video_url = meta.get("downloadAddr") or meta.get("playAddr")

        return ReelData(
            canonical_id=canonical_id(url),
            url=url,
            platform="tiktok",
            caption=caption,
            author_handle=author_handle,
            thumbnail_url=first_value(item, "covers", "cover", "thumbnailUrl"),
            video_url=video_url,
            at_handles=collect_handles(item, caption),
            tagged_location=first_value(item, "locationCreated", "locationName"),
            hashtags=normalize_hashtags(item.get("hashtags"), caption),
        )
