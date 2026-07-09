"""Fetcher interface + the normalized reel payload the pipeline consumes.

Supports Instagram reels, TikTok videos, and YouTube Shorts. Each platform has
its own fetcher, but they all return the same `ReelData` so the pipeline is
platform-agnostic.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Protocol


@dataclass
class ReelData:
    """Everything a fetcher returns about one reel/short. No video bytes are
    stored; `video_url` is a transient handle the pipeline downloads, analyzes,
    and deletes."""

    canonical_id: str
    url: str
    platform: str = "instagram"
    caption: str | None = None
    author_handle: str | None = None
    thumbnail_url: str | None = None
    video_url: str | None = None
    at_handles: list[str] = field(default_factory=list)
    tagged_location: str | None = None
    hashtags: list[str] = field(default_factory=list)


class ReelFetcher(Protocol):
    def fetch(self, url: str) -> ReelData: ...


# --- URL patterns per platform ---
_IG_RE = re.compile(r"instagram\.com/(?:reel|reels|p|tv)/([A-Za-z0-9_-]+)")
_TT_VIDEO_RE = re.compile(r"tiktok\.com/@[\w.]+/video/(\d+)")
_TT_SHORT_RE = re.compile(r"(?:vm|vt)\.tiktok\.com/([A-Za-z0-9]+)")
_TT_T_RE = re.compile(r"tiktok\.com/t/([A-Za-z0-9]+)")
_YT_SHORTS_RE = re.compile(r"youtube\.com/shorts/([A-Za-z0-9_-]+)")
_YT_WATCH_RE = re.compile(r"youtube\.com/watch\?v=([A-Za-z0-9_-]+)")
_YT_BE_RE = re.compile(r"youtu\.be/([A-Za-z0-9_-]+)")

_HANDLE_RE = re.compile(r"@([A-Za-z0-9_.]+)")
_HASHTAG_RE = re.compile(r"#([A-Za-z0-9_]+)")


def parse_source(url: str) -> tuple[str, str]:
    """Return ``(platform, canonical_id)`` for a supported link.

    canonical_id is platform-prefixed (``ig:``/``tt:``/``yt:``) so ids never
    collide across platforms. Raises ValueError for unsupported links.
    """
    if m := _IG_RE.search(url):
        return "instagram", f"ig:{m.group(1)}"
    if m := _TT_VIDEO_RE.search(url):
        return "tiktok", f"tt:{m.group(1)}"
    if m := _TT_SHORT_RE.search(url):
        return "tiktok", f"tt:{m.group(1)}"
    if m := _TT_T_RE.search(url):
        return "tiktok", f"tt:{m.group(1)}"
    if m := _YT_SHORTS_RE.search(url):
        return "youtube", f"yt:{m.group(1)}"
    if m := _YT_WATCH_RE.search(url):
        return "youtube", f"yt:{m.group(1)}"
    if m := _YT_BE_RE.search(url):
        return "youtube", f"yt:{m.group(1)}"
    raise ValueError(
        f"Unsupported link — paste an Instagram, TikTok, or YouTube link: {url!r}"
    )


def detect_platform(url: str) -> str:
    return parse_source(url)[0]


def canonical_id(url: str) -> str:
    return parse_source(url)[1]


def first_value(item: dict, *keys: str):
    """First non-empty value among the given keys (Apify actors vary in naming)."""
    for k in keys:
        v = item.get(k)
        if v:
            return v
    return None


def location_name(item: dict) -> str | None:
    loc = item.get("locationName")
    if loc:
        return loc
    nested = item.get("location")
    if isinstance(nested, dict):
        return nested.get("name") or nested.get("address")
    return None


def collect_handles(item: dict, caption: str | None) -> list[str]:
    """@handles from caption + any structured mentions/tagged users the actor gives."""
    handles = list(parse_handles(caption))
    for source in (item.get("mentions") or []):
        h = source.lstrip("@") if isinstance(source, str) else None
        if h and h not in handles:
            handles.append(h)
    for tag in item.get("taggedUsers") or []:
        username = tag.get("username") if isinstance(tag, dict) else None
        if username and username not in handles:
            handles.append(username)
    return handles


def normalize_hashtags(raw, caption: str | None) -> list[str]:
    """Actors return hashtags as list[str] or list[{name}] — normalize both."""
    out: list[str] = []
    for h in raw or []:
        if isinstance(h, str):
            out.append(h.lstrip("#"))
        elif isinstance(h, dict) and h.get("name"):
            out.append(str(h["name"]).lstrip("#"))
    return out or parse_hashtags(caption)


def parse_handles(text: str | None) -> list[str]:
    if not text:
        return []
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
