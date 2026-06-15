"""Make-or-break local test: run the extraction pipeline on one reel and print
the structured result — no DB, no queue, no app.

    python -m worker.cli --stub                 # offline sample reel
    python -m worker.cli https://instagram.com/reel/XXXX/   # real reel (needs APIFY_TOKEN)

Requires ANTHROPIC_API_KEY for the Claude call. Add --transcribe to also run
Whisper (slow; needs faster-whisper + ffmpeg).
"""
from __future__ import annotations

import argparse
import json
import sys

from worker import extract, frames
from worker.fetchers import StubFetcher, get_fetcher


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="Run reel extraction locally")
    p.add_argument("url", nargs="?", help="Instagram reel URL")
    p.add_argument("--stub", action="store_true", help="use the offline sample reel")
    p.add_argument("--transcribe", action="store_true", help="also run Whisper on the audio")
    args = p.parse_args(argv)

    if not args.stub and not args.url:
        p.error("provide a reel URL or --stub")

    data = StubFetcher().fetch(args.url or "") if args.stub else get_fetcher().fetch(args.url)
    print(f"# reel {data.canonical_id} by @{data.author_handle}", file=sys.stderr)

    sampled = frames.sample_frames(data.video_url)
    print(f"# sampled {len(sampled)} frames", file=sys.stderr)

    transcript = None
    if args.transcribe and data.video_url:
        from worker import transcribe as _t

        transcript = _t.transcribe(data.video_url)
    print(f"# transcript: {'yes' if transcript else 'none (music-only or skipped)'}", file=sys.stderr)

    result = extract.extract_places(
        caption=data.caption,
        transcript=transcript,
        at_handles=data.at_handles,
        tagged_location=data.tagged_location,
        hashtags=data.hashtags,
        frames=sampled,
    )
    print(json.dumps(result.model_dump(), indent=2, ensure_ascii=False))
    print(f"\n# extracted {len(result.places)} place(s)", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
