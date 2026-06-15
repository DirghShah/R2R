"""Fetcher interface + the normalized reel payload the pipeline consumes."""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Protocol


@dataclass
class ReelData:
    """Everything a fetcher returns about one reel. No video bytes are stored;
    `video_url` is a transient handle the pipeline downloads, analyzes, deletes."""

    canonical_id: str
    url: str
    caption: str | None = None
    author_handle: str | None = None
    thumbnail_url: str | None = None
    video_url: str | None = None
    at_handles: list[str] = field(default_factory=list)
    tagged_location: str | None = None
    hashtags: list[str] = field(default_factory=list)


class ReelFetcher(Protocol):
    def fetch(self, url: str) -> ReelData: ...


_SHORTCODE_RE = re.compile(r"instagram\.com/(?:reel|reels|p|tv)/([A-Za-z0-9_-]+)")
_HANDLE_RE = re.compile(r"@([A-Za-z0-9_.]+)")
_HASHTAG_RE = re.compile(r"#([A-Za-z0-9_]+)")


def canonical_id(url: str) -> str:
    """Normalize an Instagram reel URL to its stable shortcode for dedupe."""
    m = _SHORTCODE_RE.search(url)
    if not m:
        raise ValueError(f"Not a recognizable Instagram reel URL: {url!r}")
    return m.group(1)


def parse_handles(text: str | None) -> list[str]:
    if not text:
        return []
    # de-dupe, preserve order
    seen: dict[str, None] = {}
    for h in _HANDLE_RE.findall(text):
        seen.setdefault(h, None)
    return list(seen)


def parse_hashtags(text: str | None) -> list[str]:
    if not text:
        return []
    seen: dict[str, None] = {}
    for h in _HASHTAG_RE.findall(text):
        seen.setdefault(h, None)
    return list(seen)
