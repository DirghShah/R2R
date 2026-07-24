"""Verification harness: run the FULL analysis pipeline on one reel and show
every stage, so you can eyeball exactly what we get from each platform, what
Claude sees, and what it returns — then refine the prompt/schema with confidence.

    python -m worker.cli --stub                      # offline sample reel
    python -m worker.cli <instagram|tiktok|youtube URL>   # real reel (needs APIFY_TOKEN)

Useful flags:
    --raw               dump the untouched Apify/scraper payload (every field the platform gave)
    --save-frames DIR   write the sampled video frames as JPEGs so you can see what Claude sees
    --geocode           geocode each extracted place and show the resolved pin/rating/address
    --transcribe        also run Whisper on the audio (slow)
    --json-out FILE     write the full result bundle to a JSON file

Requires ANTHROPIC_API_KEY for the Claude call.
"""
from __future__ import annotations

import argparse
import dataclasses
import json
import sys
from pathlib import Path

from worker import extract, frames
from worker.fetchers import StubFetcher, detect_platform, get_fetcher


def _hr(title: str) -> None:
    print(f"\n{'═' * 70}\n  {title}\n{'═' * 70}", file=sys.stderr)


def _kv(label: str, value) -> None:
    print(f"  {label:<18} {value}", file=sys.stderr)


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="Run the reel analysis pipeline locally, stage by stage")
    p.add_argument("url", nargs="?", help="Instagram / TikTok / YouTube link")
    p.add_argument("--stub", action="store_true", help="use the offline sample reel (no network)")
    p.add_argument("--raw", action="store_true", help="dump the untouched platform payload")
    p.add_argument("--save-frames", metavar="DIR", help="save sampled frames as JPEGs to DIR")
    p.add_argument("--geocode", action="store_true", help="geocode each extracted place")
    p.add_argument("--transcribe", action="store_true", help="also run Whisper on the audio")
    p.add_argument("--json-out", metavar="FILE", help="write the full result bundle to JSON")
    args = p.parse_args(argv)

    if not args.stub and not args.url:
        p.error("provide a reel URL or --stub")

    # ---- Stage 1: fetch --------------------------------------------------
    platform = "stub" if args.stub else detect_platform(args.url)
    _hr(f"STAGE 1 · FETCH  ({platform})")
    if args.stub:
        data = StubFetcher().fetch(args.url or "")
    else:
        data = get_fetcher(platform).fetch(args.url)

    _kv("canonical_id", data.canonical_id)
    _kv("platform", data.platform)
    _kv("author", f"@{data.author_handle}" if data.author_handle else "(none)")
    _kv("caption", f"{len(data.caption or '')} chars")
    _kv("@handles", data.at_handles or "(none)")
    _kv("tagged_location", data.tagged_location or "(none)")
    _kv("hashtags", data.hashtags or "(none)")
    _kv("video_url", "present" if data.video_url else "(none — caption-only)")
    _kv("thumbnail_url", "present" if data.thumbnail_url else "(none)")

    if data.caption:
        _hr("CAPTION (verbatim)")
        print(data.caption, file=sys.stderr)

    if args.raw and data.raw:
        _hr("RAW PLATFORM PAYLOAD (every field the actor returned)")
        print(json.dumps(data.raw, indent=2, ensure_ascii=False, default=str), file=sys.stderr)

    # ---- Stage 2: frames -------------------------------------------------
    _hr("STAGE 2 · FRAMES")
    sampled = frames.sample_frames(data.video_url)
    _kv("frames sampled", len(sampled))
    if args.save_frames and sampled:
        out = Path(args.save_frames)
        out.mkdir(parents=True, exist_ok=True)
        for i, jpg in enumerate(sampled):
            (out / f"frame_{i:03d}.jpg").write_bytes(jpg)
        _kv("saved to", f"{out}/  ({len(sampled)} files)")

    # ---- Stage 3: transcript --------------------------------------------
    transcript = None
    if args.transcribe and data.video_url:
        from worker import transcribe as _t

        transcript = _t.transcribe(data.video_url)
    _hr("STAGE 3 · TRANSCRIPT")
    _kv("transcript", (transcript[:200] + "…") if transcript else "none (music-only or skipped)")

    # ---- Stage 4: extract (Claude) --------------------------------------
    _hr("STAGE 4 · EXTRACT  (Claude vision)")
    result = extract.extract_places(
        caption=data.caption,
        transcript=transcript,
        at_handles=data.at_handles,
        tagged_location=data.tagged_location,
        hashtags=data.hashtags,
        frames=sampled,
    )
    extraction = result.extraction
    _kv("model", extract.settings.anthropic_model)
    _kv("places found", len(extraction.places))
    _kv("primary_city", f"{extraction.primary_city}, {extraction.primary_country}")
    _kv("tokens", f"in={result.input_tokens}  out={result.output_tokens}")

    # ---- Stage 5: geocode (optional) ------------------------------------
    geocoded: list[dict] = []
    if args.geocode:
        from worker import geocode as _g

        _hr("STAGE 5 · GEOCODE")
        for ep in extraction.places:
            ep.city = ep.city or extraction.primary_city
            ep.country = ep.country or extraction.primary_country
            try:
                g = _g.geocode(ep)
            except Exception as exc:  # noqa: BLE001
                _kv(ep.name, f"ERROR: {exc}")
                geocoded.append({"name": ep.name, "error": str(exc)})
                continue
            pin = f"{g.lat:.5f},{g.lng:.5f}" if g.lat is not None else "NO PIN"
            _kv(ep.name, f"{pin}  rating={g.rating}  {g.address or ''}")
            geocoded.append(dataclasses.asdict(g))

    # ---- Full structured extraction (stdout) ----------------------------
    print(json.dumps(extraction.model_dump(), indent=2, ensure_ascii=False))

    if args.json_out:
        bundle = {
            "reel": {
                "canonical_id": data.canonical_id, "platform": data.platform,
                "author_handle": data.author_handle, "caption": data.caption,
                "at_handles": data.at_handles, "tagged_location": data.tagged_location,
                "hashtags": data.hashtags, "has_video": bool(data.video_url),
            },
            "raw_payload": data.raw or None,
            "frames_sampled": len(sampled),
            "transcript": transcript,
            "extraction": extraction.model_dump(),
            "geocoded": geocoded or None,
            "tokens": {"input": result.input_tokens, "output": result.output_tokens},
        }
        Path(args.json_out).write_text(json.dumps(bundle, indent=2, ensure_ascii=False, default=str))
        _kv("json bundle", args.json_out)

    _hr("DONE")
    _kv("places", len(extraction.places))
    _kv("tokens", f"in={result.input_tokens} out={result.output_tokens}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
