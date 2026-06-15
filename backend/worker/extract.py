"""Multi-signal place extraction from a reel, using Claude (vision).

The whole product hinges on this step. No single reel signal is complete:
- on-screen text overlays (frames) carry most place names + tips,
- the caption often carries a numbered list + @venue tags,
- audio is frequently music-only,
- @mentions / tagged location anchor geocoding.

So we hand Claude *every* available signal at once and let it reconcile them
into a deduped, schema-valid list. Structured outputs (`messages.parse` with a
Pydantic `output_format`) guarantee valid JSON — no brittle string parsing.
"""
from __future__ import annotations

import base64

import anthropic
from pydantic import BaseModel, Field

from app.config import settings

CATEGORIES = "cafe | restaurant | hotel | bar | club | sight | event | other"


class Place(BaseModel):
    name: str
    category: str = Field(description=CATEGORIES)
    city: str | None = None
    country: str | None = None
    neighborhood: str | None = Field(default=None, description="geocode hint, e.g. 'Williamsburg'")
    instagram_handle: str | None = Field(default=None, description="@venue tag without the @")
    address_hint: str | None = Field(default=None, description="literal address text seen; never invented")
    description: str = Field(description="1-2 line summary of the place from the reel")
    tips: list[str] = Field(default_factory=list, description="e.g. 'go at sunrise', 'cash only'")
    what_to_order: list[str] = Field(default_factory=list)
    sources: list[str] = Field(default_factory=list, description="any of: on_screen, caption, audio, tag")
    confidence: float = Field(description="0.0-1.0 confidence this is a real, correctly-named place")


class ReelExtraction(BaseModel):
    places: list[Place]
    overall_summary: str


class ExtractionRefused(RuntimeError):
    """Claude declined the request (safety classifier)."""


SYSTEM_PROMPT = """You extract real-world places (cafes, restaurants, hotels, \
bars, clubs, sights, events) that a short-form travel/food video recommends, so \
they can be pinned on a map.

You are given a mix of signals from one Instagram reel: the caption, the audio \
transcript (may be empty if the reel is music-only), tagged @accounts, a tagged \
location, hashtags, and a set of sampled video frames. The frames usually contain \
the most important information as on-screen TEXT OVERLAYS — read that text \
carefully; it often holds the exact place name, what to order, and tips like \
"cash only" or "go at sunrise".

Rules:
- Merge ALL signals. Cross-check them: a name seen on screen but spelled \
ambiguously can be confirmed by an @tag or the caption.
- Deduplicate: the same place mentioned on screen and in the caption is ONE place.
- Only include places the reel actually recommends or features. Do not invent \
places, and NEVER invent a street address — leave address_hint null unless real \
address text is present. Geocoding happens downstream.
- For each place set `sources` to the signals it came from (on_screen, caption, \
audio, tag) and a calibrated `confidence`. Keep low-confidence guesses but mark \
them as such rather than dropping or fabricating.
- `instagram_handle` should be the venue's @handle (without the @) when present \
— it is the strongest geocoding key.
- Pick the single best `category` per place from: %s.""" % CATEGORIES


_client: anthropic.Anthropic | None = None


def _get_client() -> anthropic.Anthropic:
    global _client
    if _client is None:
        # Reads ANTHROPIC_API_KEY from env if anthropic_api_key isn't set.
        _client = anthropic.Anthropic(api_key=settings.anthropic_api_key)
    return _client


def _image_block(jpeg_bytes: bytes) -> dict:
    return {
        "type": "image",
        "source": {
            "type": "base64",
            "media_type": "image/jpeg",
            "data": base64.standard_b64encode(jpeg_bytes).decode(),
        },
    }


def _build_text(
    *,
    caption: str | None,
    transcript: str | None,
    at_handles: list[str],
    tagged_location: str | None,
    hashtags: list[str],
) -> str:
    parts = ["Extract the recommended places from this reel.\n"]
    parts.append(f"CAPTION:\n{caption or '(none)'}")
    parts.append(f"TAGGED ACCOUNTS: {', '.join(at_handles) or '(none)'}")
    parts.append(f"TAGGED LOCATION: {tagged_location or '(none)'}")
    parts.append(f"HASHTAGS: {', '.join(hashtags) or '(none)'}")
    if transcript:
        parts.append(f"AUDIO TRANSCRIPT:\n{transcript}")
    else:
        parts.append("AUDIO TRANSCRIPT: (none — likely music-only; rely on frames + caption)")
    return "\n\n".join(parts)


def extract_places(
    *,
    caption: str | None = None,
    transcript: str | None = None,
    at_handles: list[str] | None = None,
    tagged_location: str | None = None,
    hashtags: list[str] | None = None,
    frames: list[bytes] | None = None,
) -> ReelExtraction:
    """Fuse all reel signals into a structured place list via one Claude call."""
    text = _build_text(
        caption=caption,
        transcript=transcript,
        at_handles=at_handles or [],
        tagged_location=tagged_location,
        hashtags=hashtags or [],
    )
    content: list[dict] = [{"type": "text", "text": text}]
    content += [_image_block(f) for f in (frames or [])]

    # Structured outputs constrain the response to the schema, so thinking is left
    # off here deliberately: this is a high-volume, well-scoped extraction path
    # where latency/cost matter more than open-ended reasoning.
    resp = _get_client().messages.parse(
        model=settings.anthropic_model,
        max_tokens=4000,
        system=[{"type": "text", "text": SYSTEM_PROMPT, "cache_control": {"type": "ephemeral"}}],
        messages=[{"role": "user", "content": content}],
        output_format=ReelExtraction,
    )

    if resp.stop_reason == "refusal":
        detail = getattr(resp, "stop_details", None)
        raise ExtractionRefused(f"Claude refused extraction: {detail}")

    return resp.parsed_output
