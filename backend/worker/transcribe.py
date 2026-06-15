"""Audio transcription via faster-whisper — skipped for music-only reels.

The result must never be *required*: many reels have no speech. We transcribe
when speech is present and return None otherwise, letting the extractor lean on
frames + caption.
"""
from __future__ import annotations

import shutil
import subprocess
import tempfile
from pathlib import Path

import httpx

from app.config import settings

_FFMPEG = shutil.which("ffmpeg")
_model = None  # lazy-loaded faster-whisper model


def _load_model():
    global _model
    if _model is None:
        from faster_whisper import WhisperModel  # heavy import, deferred

        _model = WhisperModel(settings.whisper_model, device="auto", compute_type="int8")
    return _model


def transcribe(video_url: str | None) -> str | None:
    """Return transcript text, or None if disabled / no speech / unavailable."""
    if not settings.enable_transcription or not video_url or not _FFMPEG:
        return None

    try:
        model = _load_model()
    except Exception:
        # faster-whisper not installed in this environment.
        return None

    with tempfile.TemporaryDirectory() as tmp:
        audio = Path(tmp) / "audio.wav"
        try:
            _extract_audio(video_url, audio)
        except Exception:
            return None

        try:
            segments, info = model.transcribe(str(audio), vad_filter=True)
            # VAD with no speech yields no segments → treat as music-only.
            text = " ".join(seg.text.strip() for seg in segments).strip()
            return text or None
        except Exception:
            return None


def _extract_audio(video_url: str, dest: Path) -> None:
    with tempfile.NamedTemporaryFile(suffix=".mp4") as vf:
        with httpx.stream("GET", video_url, timeout=120, follow_redirects=True) as r:
            r.raise_for_status()
            for chunk in r.iter_bytes():
                vf.write(chunk)
        vf.flush()
        subprocess.run(
            [_FFMPEG, "-hide_banner", "-loglevel", "error", "-y",
             "-i", vf.name, "-ar", "16000", "-ac", "1", str(dest)],
            check=True, timeout=120,
        )
