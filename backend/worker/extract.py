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
from pydantic import BaseModel, Field, ValidationError

from app.config import settings

CATEGORIES = "cafe | restaurant | hotel | bar | club | sight | event | other"

# A closed list, not free text.
#
# Left open, the model produced "bakery", "patisserie", "café" and "rotisserie"
# for what a user experiences as two or three things — which made the map's
# filter chips useless and the pin colours arbitrary.
#
# The list deliberately mixes two axes (origin: Italian, Thai; format: Pizza,
# Sushi, Bakery) because that is how people actually search for food, and how
# Yelp and Google organise it. The cost of mixing them is ambiguity — a sushi
# restaurant is both Japanese and Sushi — so PRECEDENCE is stated explicitly in
# the prompt rather than left to the model's judgement.
CUISINES = [
    # Origin
    "American", "Italian", "French", "Mexican", "Latin American", "Caribbean",
    "Chinese", "Japanese", "Korean", "Indian", "Thai", "Vietnamese",
    "Mediterranean", "Middle Eastern", "Greek", "Spanish", "African",
    # Broad fallbacks — only when nothing above fits
    "Southeast Asian", "Asian Fusion", "European",
    # Format, which wins over origin when it is the reason people go
    "Seafood", "Steakhouse", "Sushi", "Pizza", "BBQ", "Burgers",
    "Vegetarian / Vegan", "Deli / Sandwich",
    # Drink and sweet led
    "Cafe / Coffee", "Bakery", "Dessert", "Juice / Smoothie", "Tea / Boba",
    "Bar", "Nightclub / Lounge",
    # Venue shape
    "Food Hall / Market", "Street Food / Food Truck",
    "Other",
]


# Legacy and near-miss labels the model produced before the list was closed, or
# still produces occasionally. Mapping them is cheaper than re-analysing every
# reel, and keeps old pins coloured correctly.
_CUISINE_ALIASES = {
    "cafe": "Cafe / Coffee", "café": "Cafe / Coffee", "coffee": "Cafe / Coffee",
    "coffee shop": "Cafe / Coffee", "espresso": "Cafe / Coffee",
    "patisserie": "Bakery", "pastry": "Bakery", "bakery / pastry": "Bakery",
    "ice cream": "Dessert", "gelato": "Dessert", "desserts": "Dessert",
    "boba": "Tea / Boba", "bubble tea": "Tea / Boba", "tea": "Tea / Boba",
    "smoothie": "Juice / Smoothie", "juice": "Juice / Smoothie",
    "cocktail bar": "Bar", "wine bar": "Bar", "brewery": "Bar", "pub": "Bar",
    "speakeasy": "Bar", "nightclub": "Nightclub / Lounge",
    "club": "Nightclub / Lounge", "lounge": "Nightclub / Lounge",
    "ramen": "Japanese", "izakaya": "Japanese", "yakitori": "Japanese",
    "taco": "Mexican", "tacos": "Mexican", "taqueria": "Mexican",
    "vegan": "Vegetarian / Vegan", "vegetarian": "Vegetarian / Vegan",
    "plant-based": "Vegetarian / Vegan",
    "deli": "Deli / Sandwich", "sandwiches": "Deli / Sandwich",
    "sandwich": "Deli / Sandwich", "bagels": "Deli / Sandwich",
    "food truck": "Street Food / Food Truck", "street food": "Street Food / Food Truck",
    "market": "Food Hall / Market", "food hall": "Food Hall / Market",
    "rotisserie": "American", "diner": "American", "brunch": "American",
    "breakfast": "American", "southern": "American", "soul food": "American",
    "asian": "Asian Fusion", "latin": "Latin American", "halal": "Middle Eastern",
    "turkish": "Middle Eastern", "lebanese": "Middle Eastern",
    "peruvian": "Latin American", "brazilian": "Latin American",
    "filipino": "Southeast Asian", "malaysian": "Southeast Asian",
    "indonesian": "Southeast Asian", "german": "European", "british": "European",
    "portuguese": "European", "ethiopian": "African", "moroccan": "African",
}

# Atmosphere tags, closed for the same reason cuisine is: free text gave one
# idea three spellings — "cozy", "intimate", "chill vibes" — so nothing matched
# anything reliably. These are what vibe search reasons over and what the filter
# chips are built from, so consistency is the whole value.
VIBES = [
    # Atmosphere
    "Cozy", "Lively", "Quiet", "Romantic", "Aesthetic", "No-Frills",
    "Upscale", "Divey",
    # Setting
    "Outdoor Seating", "Rooftop", "Waterfront", "Garden", "Great View",
    "Hidden Gem",
    # Occasion
    "Date Spot", "Good For Groups", "Solo-Friendly", "Work-Friendly",
    "Family-Friendly", "Late Night", "Brunch",
    # Practical
    "Quick Bite", "Worth The Wait", "Reservations Needed", "Cash Only",
]

_VIBE_BY_KEY = {v.lower(): v for v in VIBES}

_VIBE_ALIASES = {
    "intimate": "Romantic", "chill": "Cozy", "chill vibes": "Cozy",
    "warm": "Cozy", "comfy": "Cozy", "homey": "Cozy", "snug": "Cozy",
    "buzzy": "Lively", "bustling": "Lively", "energetic": "Lively",
    "vibrant": "Lively", "loud": "Lively", "packed": "Lively",
    "calm": "Quiet", "peaceful": "Quiet", "relaxed": "Quiet",
    "low key": "Quiet", "low-key": "Quiet", "mellow": "Quiet",
    "date night": "Date Spot", "romantic dinner": "Date Spot",
    "instagrammable": "Aesthetic", "photogenic": "Aesthetic",
    "pretty": "Aesthetic", "beautiful": "Aesthetic", "trendy": "Aesthetic",
    "hip": "Aesthetic", "stylish": "Aesthetic", "design": "Aesthetic",
    "hole in the wall": "No-Frills", "hole-in-the-wall": "No-Frills",
    "casual": "No-Frills", "unpretentious": "No-Frills", "counter service": "No-Frills",
    "fancy": "Upscale", "fine dining": "Upscale", "elegant": "Upscale",
    "classy": "Upscale", "special occasion": "Upscale",
    "dive": "Divey", "dive bar": "Divey", "gritty": "Divey",
    "patio": "Outdoor Seating", "terrace": "Outdoor Seating",
    "al fresco": "Outdoor Seating", "sidewalk seating": "Outdoor Seating",
    "outdoor": "Outdoor Seating", "backyard": "Garden", "courtyard": "Garden",
    "rooftop bar": "Rooftop", "roof": "Rooftop",
    "waterside": "Waterfront", "by the water": "Waterfront",
    "riverside": "Waterfront", "beachfront": "Waterfront", "seaside": "Waterfront",
    "canal": "Waterfront", "harbor": "Waterfront", "harbour": "Waterfront",
    "view": "Great View", "views": "Great View", "skyline": "Great View",
    "scenic": "Great View", "panoramic": "Great View",
    "speakeasy": "Hidden Gem", "secret": "Hidden Gem", "underrated": "Hidden Gem",
    "local favorite": "Hidden Gem", "local favourite": "Hidden Gem",
    "tucked away": "Hidden Gem",
    "groups": "Good For Groups", "group dining": "Good For Groups",
    "sharing": "Good For Groups", "big tables": "Good For Groups",
    "solo": "Solo-Friendly", "bar seating": "Solo-Friendly",
    "eat alone": "Solo-Friendly", "counter seating": "Solo-Friendly",
    "study spot": "Work-Friendly", "laptop friendly": "Work-Friendly",
    "wifi": "Work-Friendly", "good for working": "Work-Friendly",
    "study": "Work-Friendly", "remote work": "Work-Friendly",
    "kid friendly": "Family-Friendly", "kids": "Family-Friendly",
    "family": "Family-Friendly",
    "open late": "Late Night", "after hours": "Late Night",
    "night owl": "Late Night", "24 hours": "Late Night",
    "breakfast": "Brunch", "morning": "Brunch", "weekend brunch": "Brunch",
    "grab and go": "Quick Bite", "takeaway": "Quick Bite", "fast": "Quick Bite",
    "counter": "Quick Bite", "on the go": "Quick Bite",
    "long line": "Worth The Wait", "queue": "Worth The Wait",
    "line out the door": "Worth The Wait", "always busy": "Worth The Wait",
    "book ahead": "Reservations Needed", "reservation": "Reservations Needed",
    "reservations": "Reservations Needed", "hard to get in": "Reservations Needed",
    "cash": "Cash Only", "no cards": "Cash Only",
}


def normalize_vibe(value: str | None) -> str | None:
    """Snap one atmosphere tag onto the closed list, or drop it.

    Unlike cuisine there is no "Other" bucket: an unrecognised vibe tag carries
    no meaning for search or filtering, and keeping it would put a chip on the
    map that matches nothing. Dropping is the honest outcome.
    """
    if not value:
        return None
    key = " ".join(value.strip().lower().split())
    if not key:
        return None
    if key in _VIBE_BY_KEY:
        return _VIBE_BY_KEY[key]
    if key in _VIBE_ALIASES:
        return _VIBE_ALIASES[key]
    # "cozy corner spot", "great for groups" — longest first so "Good For
    # Groups" beats a bare "groups".
    for canonical in sorted(VIBES, key=len, reverse=True):
        if canonical.lower() in key:
            return canonical
    for alias, canonical in sorted(_VIBE_ALIASES.items(), key=lambda kv: -len(kv[0])):
        if alias in key:
            return canonical
    return None


def normalize_vibes(values: list[str] | None) -> list[str]:
    """The whole list, deduped, order preserved, capped at four.

    Capped because a place tagged with everything is tagged with nothing, and
    the model will happily produce eight once it has a list to choose from.
    """
    out: list[str] = []
    for v in values or []:
        canonical = normalize_vibe(v)
        if canonical and canonical not in out:
            out.append(canonical)
    return out[:4]


_CUISINE_BY_KEY = {c.lower(): c for c in CUISINES}


def normalize_cuisine(value: str | None) -> str | None:
    """Snap a label onto the closed list, or return "Other".

    The tool schema asks for one of these verbatim, but non-strict tool use does
    not enforce it — so this is the actual guarantee. Without it a single
    off-list string becomes its own filter chip with a hash-derived colour.
    """
    if not value:
        return None
    key = value.strip().lower()
    if not key:
        return None
    if key in _CUISINE_BY_KEY:
        return _CUISINE_BY_KEY[key]
    if key in _CUISINE_ALIASES:
        return _CUISINE_ALIASES[key]
    # "Italian Restaurant", "Authentic Thai" — take the first list entry the
    # string mentions, longest first so "Latin American" beats "American".
    for canonical in sorted(CUISINES, key=len, reverse=True):
        if canonical.lower() in key:
            return canonical
    for alias, canonical in _CUISINE_ALIASES.items():
        if alias in key:
            return canonical
    return "Other"


class ExtractedPlace(BaseModel):
    name: str = Field(
        description="Exact proper name of the venue, correctly spelled and capitalized. "
                    "Prefer the spelling from the @handle or official on-screen text; never abbreviate."
    )
    category: str = Field(description=CATEGORIES)
    cuisine: str | None = Field(
        default=None,
        description=(
            "EXACTLY ONE label from this list, copied verbatim including spaces "
            "and slashes: " + " | ".join(CUISINES) + ". "
            "Never invent a label and never combine two. If nothing fits, use "
            "'Other'. See the precedence rule in the system prompt."
        ),
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
        description=(
            "2-4 atmosphere tags, chosen VERBATIM from this list and nothing else: "
            + ", ".join(VIBES) + ". "
            "Pick only what the reel actually shows or says — do not guess from the "
            "cuisine. Prefer specific over generic: a rooftop with a skyline shot is "
            "'Rooftop' and 'Great View', not 'Aesthetic'. Return fewer tags rather "
            "than padding to four."
        ),
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


REEL_KINDS = "venue_recommendation | advertisement | recipe_or_cooking | product_or_service | not_places"


class ReelExtraction(BaseModel):
    reel_kind: str = Field(
        default="venue_recommendation",
        description=(
            "What this reel actually IS, judged before extracting anything: " + REEL_KINDS + ". "
            "Use 'venue_recommendation' ONLY when the reel points viewers at specific, named, "
            "physically-visitable places they could walk into. "
            "'advertisement' = a sponsored/branded promo for a company rather than a genuine venue "
            "recommendation (meal-kit and delivery subscriptions like CookUnity, HelloFresh, Factor; "
            "app promos; discount-code reads). "
            "'recipe_or_cooking' = making food at home, no venue to visit. "
            "'product_or_service' = a brand, product, delivery-only/ghost kitchen or online service "
            "with no address the viewer can go to. "
            "'not_places' = anything else with no real-world venue (memes, fitness, fashion, travel "
            "vlogs that name no venue). "
            "When a reel is a genuine recommendation of real venues that ALSO carries a sponsorship, "
            "it is still 'venue_recommendation'."
        ),
    )
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

## First decide what the reel IS

Before extracting anything, set `reel_kind`. ReelMap pins places on a map, so the only reels worth \
extracting are ones recommending **specific, named, physically-visitable venues**.

Set `reel_kind` to something other than `venue_recommendation` — and return an EMPTY `places` list — when:
- It's an **ad** for a company rather than a venue recommendation: meal-kit or delivery subscriptions \
(CookUnity, HelloFresh, Factor, Blue Apron), app promos, discount-code reads, brand sponsorships \
where the brand itself is the subject.
- It's a **recipe / cooking** video — food made at home, nowhere to visit.
- It's a **product or online service**, including delivery-only brands and ghost kitchens with no \
address a viewer could walk into.
- It features **no named real-world venue at all**.

The test is simple: *could a viewer physically go there?* A meal-kit brand ships you a box — that is \
not a place, and must never be pinned. A restaurant that happens to be sponsoring the reel still is.

A genuine venue recommendation that also carries a sponsorship stays `venue_recommendation`.

## Completeness is the #1 priority

A numbered caption list (1. … 2. … 3. …) is the gold standard — every numbered item IS a real \
place recommendation. Extract ALL of them. Never skip a place because it seems obscure or hard \
to geocode. Geocoding happens downstream; your job is to surface every place in the reel.

If the caption says "9 best cafes in Dallas" and lists 9 places with @handles, you MUST return \
exactly 9 places.

**Only output places you can NAME.** Completeness means every *nameable* place. If a venue appears \
on-screen but you cannot read its actual name from any signal (caption, tags, or legible on-screen \
text), OMIT it entirely — do not invent a name and never emit a placeholder like "Unknown", \
"<UNKNOWN>", "Cafe", or a description in the `name` field. An unnamed place cannot be pinned and is \
worse than leaving it out.

## Signal fusion rules

- **Merge** all signals. A name seen on-screen confirmed by an @tag or caption item is one place.
- **Deduplicate**: the same place from multiple signals = one entry, not two.
- **City/country inference**: use every available clue (tagged location, caption text, hashtags, \
on-screen text) to infer the city and country for each place. Set `primary_city` / `primary_country` \
at the top level, then inherit them for all places unless a specific place clearly belongs elsewhere.
- **Exclude the reel's own creator.** The CREATOR account (the poster/reviewer) is NOT a place — \
never output it as a venue, even when it's @-mentioned in the caption ("another spot is linked @theirhandle"). \
Only extract venues the reel actually features or recommends.
- **Instagram handle**: extract the @handle (without @) from caption mentions like `@ottoscoffee` \
or `@funnylibrarycoffee` — this is the strongest geocoding key and must always be captured.
- **Tagged address**: when a precise street address is provided (TAGGED ADDRESS), it belongs to the \
reel's primary venue — use it to fix that place's city/neighborhood.
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

## Cuisine — one label, from the list, verbatim

`cuisine` must be EXACTLY one string from the allowed list. Copy it character for
character, including spaces and slashes ("Cafe / Coffee", not "Cafe" or "coffee").
Never invent a label, never combine two, never leave it null for a food place.

**Precedence, when a place fits more than one — apply in order:**

1. **Format wins when it is the reason people go.** A sushi restaurant is
   `Sushi`, not `Japanese`. A pizzeria is `Pizza`, not `Italian`. A BBQ joint is
   `BBQ`, not `American`. A steakhouse is `Steakhouse`. A burger place is
   `Burgers`. A place known for seafood is `Seafood`.
2. **Otherwise use the origin.** A broad Italian trattoria is `Italian`. A
   Korean restaurant serving many dishes is `Korean`.
3. **Drink- or sweet-led beats the food origin.** A French patisserie is
   `Bakery`. An Italian gelateria is `Dessert`. A Vietnamese coffee shop is
   `Cafe / Coffee`. A boba shop is `Tea / Boba`.
4. **`Southeast Asian`, `Asian Fusion` and `European` are last resorts.** Use
   them only when no specific country or format above fits — never for a place
   that is clearly Thai, Vietnamese, Italian or French.
5. **`Other` when nothing fits at all.** Better than a wrong label.

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
    author_handle: str | None = None,
    tagged_address: str | None = None,
) -> str:
    parts = ["Extract the recommended places from this reel.\n"]
    parts.append(f"CAPTION:\n{caption or '(none)'}")
    parts.append(
        f"CREATOR (the account that POSTED this reel — the reviewer, NOT a place): "
        f"@{author_handle}" if author_handle else "CREATOR: (unknown)"
    )
    parts.append(f"TAGGED ACCOUNTS: {', '.join(at_handles) or '(none)'}")
    parts.append(f"TAGGED LOCATION: {tagged_location or '(none)'}")
    parts.append(f"TAGGED ADDRESS: {tagged_address or '(none)'}")
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


# We extract via a *forced tool call* rather than `messages.parse`
# (output_config.format). Structured outputs compile the schema into a
# decoding grammar server-side; our nested places-list schema is complex enough
# that the compile can exceed the server limit ("400 Grammar compilation timed
# out"). Non-strict tool use fills the same schema without grammar compilation,
# and we validate the result with Pydantic + one repair retry.
_TOOL_NAME = "record_reel_places"


def _extraction_tool() -> dict:
    return {
        "name": _TOOL_NAME,
        "description": "Record the structured list of every place the reel recommends or features.",
        "input_schema": ReelExtraction.model_json_schema(),
    }


def extract_places(
    *,
    caption: str | None = None,
    transcript: str | None = None,
    at_handles: list[str] | None = None,
    tagged_location: str | None = None,
    hashtags: list[str] | None = None,
    frames: list[bytes] | None = None,
    author_handle: str | None = None,
    tagged_address: str | None = None,
) -> ExtractionResult:
    """Fuse all reel signals into a structured place list via one Claude call."""
    text = _build_text(
        caption=caption,
        transcript=transcript,
        at_handles=at_handles or [],
        tagged_location=tagged_location,
        hashtags=hashtags or [],
        author_handle=author_handle,
        tagged_address=tagged_address,
    )
    content: list[dict] = [{"type": "text", "text": text}]
    content += [_image_block(f) for f in (frames or [])]

    tool = _extraction_tool()
    last_error: Exception | None = None
    # Two attempts: a truncated or malformed tool call (rare with forced tool
    # use) is retried once before we give up and fail the reel.
    for _ in range(2):
        resp = _get_client().messages.create(
            model=settings.anthropic_model,
            max_tokens=8000,
            system=[{"type": "text", "text": SYSTEM_PROMPT, "cache_control": {"type": "ephemeral"}}],
            messages=[{"role": "user", "content": content}],
            tools=[tool],
            tool_choice={"type": "tool", "name": _TOOL_NAME},
        )

        if resp.stop_reason == "refusal":
            detail = getattr(resp, "stop_details", None)
            raise ExtractionRefused(f"Claude refused extraction: {detail}")

        tool_use = next(
            (b for b in resp.content if getattr(b, "type", None) == "tool_use" and b.name == _TOOL_NAME),
            None,
        )
        if tool_use is None:
            last_error = RuntimeError("Claude returned no extraction tool call")
            continue

        try:
            extraction = ReelExtraction.model_validate(tool_use.input)
        except ValidationError as exc:
            last_error = exc
            continue

        usage = resp.usage
        return ExtractionResult(
            extraction=extraction,
            input_tokens=getattr(usage, "input_tokens", 0) or 0,
            output_tokens=getattr(usage, "output_tokens", 0) or 0,
        )

    raise RuntimeError(f"extraction failed to produce valid output: {last_error}")
