"""Transient video handling: obtain a reel's video, sample scene-change frames,
discard.

We never persist the video. Frames are returned as in-memory JPEG bytes and the
temp file is deleted immediately. Scene-change detection (vs fixed interval) is
what captures each place's segment + its on-screen text overlay in a list reel.

Two ways to get the video, tried in order:
  1. The direct CDN media URL the fetcher already extracted (fast, no extra deps).
  2. yt-dlp against the canonical reel page URL — the universal fallback that
     works across Instagram, TikTok, and YouTube when the actor doesn't return a
     usable media URL (or returns a watch-page URL, or a link that 403s/expires).

Every failure degrades gracefully to an empty list, so extraction always
continues on caption + tags even when no frames can be pulled.
"""
from __future__ import annotations

import logging
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

import httpx

log = logging.getLogger(__name__)

_FFMPEG = shutil.which("ffmpeg")
_MAX_FRAMES = 12
_DOWNLOAD_TIMEOUT = 120   # seconds, direct httpx download
_YTDLP_TIMEOUT = 180      # seconds, yt-dlp download (slower; it resolves formats)


class _NotAVideo(RuntimeError):
    """The URL served HTML/text, not video bytes (usually a platform watch page)."""


def sample_frames(
    video_url: str | None,
    *,
    page_url: str | None = None,
    max_frames: int = _MAX_FRAMES,
) -> list[bytes]:
    """Return up to `max_frames` JPEGs sampled from the reel. Empty list on any
    failure (degrade gracefully to caption-only extraction).

    `video_url` is a direct media URL (tried first); `page_url` is the canonical
    reel link used for the yt-dlp fallback. At least one should be provided.
    """
    if not _FFMPEG:
        # ffmpeg not installed — pipeline still works on caption + tags.
        return []

    with tempfile.TemporaryDirectory() as tmp:
        tmpdir = Path(tmp)

        video = _obtain_video(video_url, page_url, tmpdir)
        if video is None:
            return []
        return _extract_frames(video, tmpdir, max_frames)


def _obtain_video(video_url: str | None, page_url: str | None, tmpdir: Path) -> Path | None:
    """Get a playable local video file, trying the direct URL then yt-dlp."""
    # 1) Direct CDN download — fastest when the fetcher gave us a real media URL.
    if video_url:
        dest = tmpdir / "direct.mp4"
        try:
            _download(video_url, dest)
            if dest.stat().st_size > 0:
                return dest
        except _NotAVideo as exc:
            log.info("direct video_url was not a video (%s) — trying yt-dlp", exc)
        except Exception:  # noqa: BLE001 - network/format issue; fall through to yt-dlp
            log.info("direct video download failed — trying yt-dlp", exc_info=True)

    # 2) yt-dlp against the reel page — the universal, platform-agnostic fallback.
    if page_url:
        got = _ytdlp_download(page_url, tmpdir)
        if got is not None:
            return got

    return None


def _download(video_url: str, dest: Path) -> None:
    with httpx.stream("GET", video_url, timeout=_DOWNLOAD_TIMEOUT, follow_redirects=True) as r:
        r.raise_for_status()
        # A fetcher that falls back to the platform watch page (tiktok.com/@…/video,
        # youtube.com/shorts/…) hands us an HTML document. Downloading it and feeding
        # it to ffmpeg yields a confusing "moov atom not found" — bail early instead.
        ctype = r.headers.get("content-type", "").lower()
        if ctype.startswith(("text/", "application/xhtml", "application/json")):
            raise _NotAVideo(f"expected video, got {ctype!r} from {video_url[:60]}")
        with dest.open("wb") as f:
            for chunk in r.iter_bytes():
                f.write(chunk)


def _ytdlp_download(page_url: str, tmpdir: Path) -> Path | None:
    """Download the reel with yt-dlp. Returns the local file, or None on any
    failure (yt-dlp missing, private/geo-blocked reel, timeout, unsupported URL)."""
    out_tmpl = str(tmpdir / "ytdl.%(ext)s")
    # Run via the interpreter so we don't depend on the console script being on
    # PATH. A single ≤720p progressive stream is plenty for OCR-quality frames
    # and avoids a separate audio+video merge step.
    cmd = [
        sys.executable, "-m", "yt_dlp",
        "-q", "--no-warnings", "--no-playlist", "--no-part",
        "--socket-timeout", "30",
        "-f", "best[height<=720][ext=mp4]/best[ext=mp4]/best",
        "-o", out_tmpl, page_url,
    ]
    try:
        subprocess.run(
            cmd, check=True, timeout=_YTDLP_TIMEOUT,
            stdout=subprocess.DEVNULL, stderr=subprocess.PIPE,
        )
    except FileNotFoundError:
        log.warning("yt-dlp not available (pip install yt-dlp) — no frames for %s", page_url[:60])
        return None
    except subprocess.CalledProcessError as exc:
        detail = (exc.stderr or b"").decode("utf-8", "replace").strip().splitlines()
        log.info("yt-dlp failed for %s: %s", page_url[:60], detail[-1] if detail else "unknown")
        return None
    except Exception:  # noqa: BLE001 - timeout / unexpected
        log.info("yt-dlp errored for %s", page_url[:60], exc_info=True)
        return None

    files = sorted(p for p in tmpdir.glob("ytdl.*") if p.is_file() and p.stat().st_size > 0)
    return files[0] if files else None


def _extract_frames(video: Path, tmpdir: Path, max_frames: int) -> list[bytes]:
    """Scene-change frames via ffmpeg; fall back to evenly-spaced frames if the
    clip has no distinct scene cuts. Empty list if ffmpeg can't read the file."""
    out_pattern = str(tmpdir / "frame_%03d.jpg")

    def _run(vf: str) -> list[Path]:
        cmd = [
            _FFMPEG, "-hide_banner", "-loglevel", "error", "-i", str(video),
            "-vf", vf, "-vsync", "vfr", "-frames:v", str(max_frames), out_pattern,
        ]
        try:
            subprocess.run(cmd, check=True, timeout=120)
        except Exception:  # noqa: BLE001 - unreadable/corrupt file
            return []
        return sorted(tmpdir.glob("frame_*.jpg"))

    frames = _run("select='gt(scene,0.3)',scale=640:-1")
    if not frames:
        # No distinct scenes (or scene filter produced nothing) — even spacing.
        frames = _run("fps=1/2,scale=640:-1")

    return [p.read_bytes() for p in frames[:max_frames]]
