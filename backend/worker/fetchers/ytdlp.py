"""yt-dlp fetcher — the second path when the scraping service breaks.

This exists for resilience, not compliance. Apify and yt-dlp are the same
category of access; what differs is the failure mode, and that is the point.
Apify is a hosted service with its own proxy pool and actor code, maintained by
one vendor. yt-dlp is a local extractor with thousands of contributors that
typically ships a fix within days of a platform change. When one breaks the
other usually still works, which is the whole argument for having both.

Known weaknesses, stated plainly:
  - Instagram is the platform yt-dlp struggles with most; TikTok and YouTube
    are considerably more reliable.
  - Datacenter IPs get rate-limited without proxies, and Railway is a
    datacenter IP.
  - It is slower, because it resolves formats before returning.

So this is a fallback, not a replacement.
"""
from __future__ import annotations

import json
import logging
import shutil
import subprocess

from .base import (
    ReelData,
    canonical_id,
    detect_platform,
    parse_handles,
    parse_hashtags,
)

log = logging.getLogger(__name__)

_YTDLP = shutil.which("yt-dlp")
_TIMEOUT = 120


class YtDlpUnavailable(RuntimeError):
    """yt-dlp isn't installed in this image."""


class YtDlpFetcher:
    """Metadata via `yt-dlp --dump-json`, without downloading the video.

    The pipeline downloads media separately (worker/frames.py), so this only
    needs the JSON — which is much faster than a full fetch and avoids paying
    the download cost twice.
    """

    def fetch(self, url: str) -> ReelData:
        if not _YTDLP:
            raise YtDlpUnavailable("yt-dlp is not installed")

        proc = subprocess.run(
            [
                _YTDLP,
                "--dump-single-json",
                "--no-warnings",
                "--no-playlist",
                # Metadata only. The pipeline fetches media itself, and asking
                # yt-dlp to download here would double the work and the time.
                "--skip-download",
                url,
            ],
            capture_output=True,
            timeout=_TIMEOUT,
            check=False,
        )
        if proc.returncode != 0:
            detail = proc.stderr.decode("utf-8", "replace").strip().splitlines()
            raise RuntimeError(f"yt-dlp failed: {detail[-1] if detail else 'unknown error'}")

        info = json.loads(proc.stdout)
        platform = detect_platform(url)

        # yt-dlp normalises across sites but not perfectly: the caption lives in
        # `description` for most extractors and `title` for a few.
        caption = info.get("description") or info.get("title")

        return ReelData(
            canonical_id=canonical_id(url),
            url=url,
            platform=platform,
            caption=caption,
            author_handle=(
                info.get("uploader_id")
                or info.get("channel_id")
                or info.get("uploader")
            ),
            thumbnail_url=info.get("thumbnail"),
            # A direct media URL when yt-dlp resolved one. frames.py falls back
            # to running yt-dlp itself if this is absent, so a miss is not fatal.
            video_url=info.get("url"),
            at_handles=list(parse_handles(caption)),
            tagged_location=info.get("location"),
            hashtags=info.get("tags") or list(parse_hashtags(caption)),
            raw=info,
        )
