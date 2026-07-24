"""Multi-signal place extraction from a reel, using Claude (vision).

The whole product hinges on this step. No single reel signal is complete:
- on-screen text overlays (frames) carry most place names + tips,
- the caption often carries a numbered list + @venue tags,
- audio is frequently music-only,
- @mentions / tagged location anchor geocoding.

We hand Claude *every* available signal at once and let it reconcile them
into a deduped, schema-valid list. Structured outputs (`messages.parse` with a
Pydantic `output_format`) guarantee valid JSON — no brittle string parsing.
"""
from __future__ import annotations

import base64
from dataclasses import dataclass

import anthropic
from pydantic import BaseModel, Field

from app.config import settings

CATEGORIES = "cafe | restaurant | hotel | bar | club | sight | event | other"


class ExtractedPlace(BaseModel):
    name: str = Field(
        description="Exact proper name of the venue, correctly spelled and capitalized. "
                    "Prefer the spelling from the @handle or official on-screen text; never abbreviate."
    )
    category: str = Field(description=CATEGORIES)
    cuisine: str | None = Field(
        default=None,
        description="Short cuisine or venue-type label for filtering & display, Title Case. "
                    "For food: e.g. 'Italian', 'Japanese', 'Mexican', 'Thai', 'Greek', 'Seafood', "
                    "'Café', 'Bakery', 'Cocktail Bar', 'Wine Bar', 'Nightclub'. "
                    "For non-food places (hotels, sights) leave null.",
    )
    city: str | None = Field(default=None, description="City, inferred from all signals")
    country: str | None = Field(default=None, description="Country, inferred from all signals")
    neighborhood: str | None = Field(default=None, description="Neighborhood/district e.g. 'Bishop Arts'")
    instagram_handle: str | None = Field(
        default=None,
        description="Venue's @handle without the @. Strongest geocoding key — always capture.",
    )
    website: str | None = Field(
        default=None,
        description="Full URL if visible or confidently inferable from the handle. Null if unsure.",
    )
    description: str = Field(
        description="2-3 vivid sentences about what makes this place special. Write as a recommendation."
    )
    vibe: list[str] = Field(
        default_factory=list,
        description="2-4 atmosphere tags from what the reel shows: e.g. 'cozy', 'study spot', 'aesthetic'.",
    )
    tips: list[str] = Field(
        default_factory=list,
        description="Practical tips from the reel: hours quirks, must-knows, ordering advice.",
    )
    what_to_order: list[str] = Field(
        default_factory=list,
        description="Specific menu items called out in the reel.",
    )
    price_level: int | None = Field(
        default=None,
        description="1=$  2=$$  3=$$$  4=$$$$ — only set if mentioned or clearly implied.",
    )
    hours_hint: str | None = Field(
        default=None,
        description="Hours info if mentioned e.g. 'open late', 'breakfast only'.",
    )
    confidence: float = Field(
        description="0–1. Caption numbered list + @handle = ≥ 0.9. Ambiguous = lower."
    )


class ReelExtraction(BaseModel):
    places: list[ExtractedPlace]
    overall_summary: str
    primary_city: str | None = Field(
        default=None,
        description="Main city this reel is about.",
    )
    primary_country: str | None = Field(
        default=None,
        description="Country of the main city.",
    )


class ExtractionRefused(RuntimeError):
    """Claude declined the request (safety classifier)."""


@dataclass
class ExtractionResult:
    extraction: ReelExtraction
    input_tokens: int
    output_tokens: int


SYSTEM_PROMPT = """You extract every real-world place (cafes, restaurants, hotels, bars, clubs, \
sights, events) that a short-form travel/food reel recommends or features, so they can be pinned on a map.

You receive a mix of signals: the caption, audio transcript (often empty/music-only), \
tagged @accounts, a tagged location, hashtags, and sampled video frames. The frames frequently \
contain on-screen TEXT OVERLAYS — read every word carefully; they hold place names, menu items, \
tips, and addresses.

## Completeness is the #1 priority

A numbered caption list (1. … 2. … 3. …) is the gold standard — every numbered item IS a real \
place recommendation. Extract ALL of them. Never skip a place because it seems obscure or hard \
to geocode. Geocoding happens downstream; your job is to surface every place in the reel.

If the caption says "9 best cafes in Dallas" and lists 9 places with @handles, you MUST return \
exactly 9 places.

## Signal fusion rules

- **Merge** all signals. A name seen on-screen confirmed by an @tag or caption item is one place.
- **Deduplicate**: the same place from multiple signals = one entry, not two.
- **City/country inference**: use every available clue (tagged location, caption text, hashtags, \
on-screen text) to infer the city and country for each place. Set `primary_city` / `primary_country` \
at the top level, then inherit them for all places unless a specific place clearly belongs elsewhere.
- **Instagram handle**: extract the @handle (without @) from caption mentions like `@ottoscoffee` \
or `@funnylibrarycoffee` — this is the strongest geocoding key and must always be captured.
- **Website**: if the venue's website URL is visible in the video or caption, include it. \
If you can confidently infer it from the handle (e.g. @ottoscoffee → https://ottoscoffee.com, \
@lalalandkindcafe → https://lalalandkindcafe.com), include it. Leave null when uncertain.
- **Vibe/atmosphere**: extract 2-5 tags from what the video actually shows (music, color palette, \
crowd, lighting, seating style) and what the creator says. Don't invent; only tag what the reel conveys.
- **Tips**: pull every practical tip from audio, on-screen text, and caption descriptions. \
The caption often has the richest tip content ("fuel your jet lag", "buy a book and enjoy a coffee for free").
- **What to order**: note any specific items called out visually or verbally.
- **Price level**: only set if mentioned or clearly shown ($, $$, etc.).
- **Confidence**: places named in a numbered caption list with an @handle are ≥ 0.9. \
Partially-seen or ambiguous places may be lower. Keep low-confidence places — mark them, don't drop them.
- **Do NOT invent addresses** — leave `address_hint` null unless literal address text is present.

Pick the single best `category` per place from: %s.""" % CATEGORIES


_client: anthropic.Anthropic | None = None


def _get_client() -> anthropic.Anthropic:
    global _client
    if _client is None:
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

    # Count numbered items in caption as an explicit completeness hint
    if caption:
        numbered = [ln.strip() for ln in caption.splitlines() if ln.strip()[:2].rstrip(".").isdigit()]
        if numbered:
            parts.append(
                f"\nNOTE: The caption contains {len(numbered)} numbered items. "
                f"Your response MUST include all {len(numbered)} as separate places."
            )

    return "\n\n".join(parts)


def extract_places(
    *,
    caption: str | None = None,
    transcript: str | None = None,
    at_handles: list[str] | None = None,
    tagged_location: str | None = None,
    hashtags: list[str] | None = None,
    frames: list[bytes] | None = None,
) -> ExtractionResult:
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

    resp = _get_client().messages.parse(
        model=settings.anthropic_model,
        max_tokens=6000,
        system=[{"type": "text", "text": SYSTEM_PROMPT, "cache_control": {"type": "ephemeral"}}],
        messages=[{"role": "user", "content": content}],
        output_format=ReelExtraction,
    )

    if resp.stop_reason == "refusal":
        detail = getattr(resp, "stop_details", None)
        raise ExtractionRefused(f"Claude refused extraction: {detail}")

    usage = resp.usage
    return ExtractionResult(
        extraction=resp.parsed_output,
        input_tokens=getattr(usage, "input_tokens", 0) or 0,
        output_tokens=getattr(usage, "output_tokens", 0) or 0,
    )
