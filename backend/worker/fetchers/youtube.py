"""YouTube Shorts fetcher via Apify.

The title + description carry most of the place info for Shorts (plus on-screen
text via frames). Field names depend on the chosen actor (default:
streamers/youtube-scraper); mapping is defensive. Adjust keys here or point
APIFY_ACTOR_YOUTUBE at a different actor if a real Short returns thin data.
"""
from __future__ import annotations

from app.config import settings

from .base import ReelData, canonical_id, collect_handles, first_value, normalize_hashtags
from .instagram import apify_run


class YouTubeFetcher:
    def fetch(self, url: str) -> ReelData:
        item = apify_run(settings.apify_actor_youtube,
                         {"startUrls": [{"url": url}], "maxResults": 1})
        title = first_value(item, "title", "name") or ""
        description = first_value(item, "text", "description", "descriptionText") or ""
        # Title often names the topic; fold it into the caption for extraction.
        caption = f"{title}\n\n{description}".strip()

        return ReelData(
            canonical_id=canonical_id(url),
            url=url,
            platform="youtube",
            caption=caption or None,
            author_handle=first_value(item, "channelName", "channelUsername", "author"),
            thumbnail_url=first_value(item, "thumbnailUrl", "thumbnail"),
            video_url=first_value(item, "downloadUrl", "videoUrl", "url"),
            at_handles=collect_handles(item, caption),
            tagged_location=None,
            hashtags=normalize_hashtags(item.get("hashtags"), caption),
            raw=item,
        )
