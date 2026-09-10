"""Search saved places by what they feel like, not what they're called.

The app's search box already filters by name instantly and offline. This is the
other half: "somewhere quiet I can actually work", "impressive but not stuffy,
for a second date", "a cafe by the water". Queries like those are compositional
— they combine atmosphere, setting and occasion — which is why they go to a
model rather than to a keyword index.

No embeddings and no vector store. A person's saved places number in the tens
or low hundreds, so the whole candidate set fits in one prompt, and a model that
can *read* the descriptions beats cosine similarity over them. It also means no
second vendor and no index to keep in sync with the database.

The ceiling is the data: this can only find what a reel actually said. A place
nobody described as waterfront will not turn up for "by the water", however the
question is phrased.
"""
from __future__ import annotations

import json
import logging
from dataclasses import dataclass

from anthropic import Anthropic

from app.config import settings

log = logging.getLogger(__name__)

_TOOL_NAME = "return_matches"

SYSTEM_PROMPT = """\
You match a person's saved restaurants and cafés against how they describe what \
they're in the mood for.

You are given their saved places and one query. Return only the places that \
genuinely fit, best first, each with a short reason quoting what in the place's \
own data made it match.

Rules:
- Only use what each place's data actually says. Never infer that a place is \
waterfront, quiet or good for groups because its cuisine or name suggests it.
- Returning nothing is correct when nothing fits. A wrong match is worse than \
an empty result, because it teaches the person the search doesn't work.
- Return at most 12, and fewer when only a few genuinely fit.
- The reason is one short clause, under 12 words, addressed to the person: \
"tagged cozy and work-friendly", "the reel called it a rooftop with skyline views".
- Match intent, not words. "Somewhere to bring my parents" means calm, \
family-friendly, not divey. "Impress a date" means upscale or romantic, not \
quick bite.
"""


@dataclass
class VibeMatch:
    place_id: str
    reason: str


@dataclass
class VibeSearchResult:
    matches: list[VibeMatch]
    input_tokens: int
    output_tokens: int


def _tool() -> dict:
    return {
        "name": _TOOL_NAME,
        "description": "Return the saved places that match the query, best first.",
        "input_schema": {
            "type": "object",
            "properties": {
                "matches": {
                    "type": "array",
                    "description": "Matching places, best first. Empty if none fit.",
                    "items": {
                        "type": "object",
                        "properties": {
                            "place_id": {
                                "type": "string",
                                "description": "The id, copied exactly from the list given.",
                            },
                            "reason": {
                                "type": "string",
                                "description": "One short clause, under 12 words, "
                                               "citing what in this place's data matched.",
                            },
                        },
                        "required": ["place_id", "reason"],
                    },
                }
            },
            "required": ["matches"],
        },
    }


def _catalogue_line(p: dict) -> str:
    """One compact line per place. Short on purpose — this is multiplied by the
    number of places a person has saved, and it is the whole input cost."""
    bits = [f"id={p['id']}", p["name"]]
    if p.get("cuisine"):
        bits.append(p["cuisine"])
    if p.get("category"):
        bits.append(p["category"])
    if p.get("city"):
        bits.append(p["city"])
    if p.get("vibes"):
        bits.append("vibe: " + ", ".join(p["vibes"]))
    if p.get("price_level"):
        bits.append("$" * int(p["price_level"]))
    if p.get("rating"):
        bits.append(f"{p['rating']}★")
    if p.get("description"):
        bits.append(p["description"])
    return " | ".join(bits)


def search(query: str, places: list[dict]) -> VibeSearchResult:
    """Rank `places` against `query`. Never raises for a bad model response.

    `places` are dicts with at least `id` and `name`; anything else present is
    used. Ids in the answer are checked against the ones sent, because a model
    asked for an identifier will occasionally invent a plausible one and a
    hallucinated id would surface someone else's place or none at all.
    """
    if not query.strip() or not places:
        return VibeSearchResult([], 0, 0)

    catalogue = "\n".join(_catalogue_line(p) for p in places)
    prompt = (
        f"Saved places:\n{catalogue}\n\n"
        f"They are looking for: {query.strip()}"
    )

    client = Anthropic(api_key=settings.anthropic_api_key)
    resp = client.messages.create(
        model=settings.anthropic_model,
        max_tokens=2000,
        system=[{"type": "text", "text": SYSTEM_PROMPT,
                 "cache_control": {"type": "ephemeral"}}],
        messages=[{"role": "user", "content": prompt}],
        tools=[_tool()],
        tool_choice={"type": "tool", "name": _TOOL_NAME},
    )

    usage = resp.usage
    in_tok = getattr(usage, "input_tokens", 0) or 0
    out_tok = getattr(usage, "output_tokens", 0) or 0

    block = next(
        (b for b in resp.content
         if getattr(b, "type", None) == "tool_use" and b.name == _TOOL_NAME),
        None,
    )
    if block is None:
        log.warning("vibe search: no tool call for %r", query)
        return VibeSearchResult([], in_tok, out_tok)

    valid_ids = {p["id"] for p in places}
    matches: list[VibeMatch] = []
    seen: set[str] = set()
    for raw in (block.input or {}).get("matches", []):
        if not isinstance(raw, dict):
            continue
        pid = str(raw.get("place_id", "")).strip()
        # A model asked for an identifier will occasionally invent one.
        if pid not in valid_ids or pid in seen:
            continue
        seen.add(pid)
        matches.append(VibeMatch(place_id=pid, reason=str(raw.get("reason", "")).strip()[:120]))

    log.info("vibe search %r -> %d/%d matches (%d in, %d out tokens)",
             query, len(matches), len(places), in_tok, out_tok)
    return VibeSearchResult(matches, in_tok, out_tok)


def catalogue_json(places: list[dict]) -> str:
    """Debug helper: what the model actually sees."""
    return json.dumps([_catalogue_line(p) for p in places], indent=2)
