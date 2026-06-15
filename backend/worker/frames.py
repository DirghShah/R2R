"""Transient video handling: download a reel, sample scene-change frames, discard.

We never persist the video. Frames are returned as in-memory JPEG bytes and the
temp file is deleted immediately. Scene-change detection (vs fixed interval) is
what captures each place's segment + its on-screen text overlay in a list reel.
"""
from __future__ import annotations

import shutil
import subprocess
import tempfile
from pathlib import Path

import httpx

_FFMPEG = shutil.which("ffmpeg")
_MAX_FRAMES = 12


def _download(video_url: str, dest: Path) -> None:
    with httpx.stream("GET", video_url, timeout=120, follow_redirects=True) as r:
        r.raise_for_status()
        with dest.open("wb") as f:
            for chunk in r.iter_bytes():
                f.write(chunk)


def sample_frames(video_url: str | None, *, max_frames: int = _MAX_FRAMES) -> list[bytes]:
    """Return up to `max_frames` JPEGs at scene changes. Empty list on any failure
    (degrade gracefully to caption-only extraction)."""
    if not video_url:
        return []
    if not _FFMPEG:
        # ffmpeg not installed — pipeline still works on caption + tags.
        return []

    with tempfile.TemporaryDirectory() as tmp:
        tmpdir = Path(tmp)
        video = tmpdir / "reel.mp4"
        try:
            _download(video_url, video)
        except Exception:
            return []

        out_pattern = str(tmpdir / "frame_%03d.jpg")
        # Pick scene-change frames; fall back to ~1 fps if no scenes detected.
        cmd = [
            _FFMPEG, "-hide_banner", "-loglevel", "error", "-i", str(video),
            "-vf", "select='gt(scene,0.3)',scale=640:-1",
            "-vsync", "vfr", "-frames:v", str(max_frames), out_pattern,
        ]
        try:
            subprocess.run(cmd, check=True, timeout=120)
        except Exception:
            return []

        frames = sorted(tmpdir.glob("frame_*.jpg"))
        if not frames:
            # No distinct scenes — grab evenly-spaced frames instead.
            cmd = [
                _FFMPEG, "-hide_banner", "-loglevel", "error", "-i", str(video),
                "-vf", "fps=1/2,scale=640:-1", "-frames:v", str(max_frames), out_pattern,
            ]
            try:
                subprocess.run(cmd, check=True, timeout=120)
            except Exception:
                return []
            frames = sorted(tmpdir.glob("frame_*.jpg"))

        return [p.read_bytes() for p in frames[:max_frames]]
