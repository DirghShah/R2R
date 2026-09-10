"""Resolve an extracted place to real coordinates + enrichment.

Strategy: build the best text query we can (prefer the @handle for Google,
readable name for Nominatim), hit Google Places Text Search → Place Details for
coords, address, rating, photos, hours. Falls back to OpenStreetMap Nominatim
when no Google key is configured.

Geocoding NEVER drops a place. When no match is found, we return a partial
GeocodeResult (lat/lng = None) so the place is still saved and appears in lists
— it just won't have a map pin. The iOS app already handles this: MapScreen
filters `coordinate != nil`, CityListsScreen shows everything.
"""
from __future__ import annotations

import difflib
import logging
from dataclasses import dataclass, field

import httpx

from app.config import settings

log = logging.getLogger(__name__)

# Places API (New) — field masks pick the billing tier, so we do TWO steps:
# a cheap Pro-tier Text Search to find + score candidates, then an Enterprise
# Place Details ONLY on the accepted one (rating/reviews/hours/photos/phone).
_PLACES_TEXT = "https://places.googleapis.com/v1/places:searchText"
_PLACES_DETAILS = "https://places.googleapis.com/v1/places/{place_id}"
_PLACES_MEDIA = "https://places.googleapis.com/v1/{photo_name}/media"
_TEXT_FIELD_MASK = ",".join([
    "places.id", "places.displayName", "places.formattedAddress",
    "places.location", "places.types", "places.primaryType", "places.businessStatus",
    # Carries the state/province code. Needed here because with lazy enrichment
    # the Details call — which used to supply it — may never run. Address
    # components are already inside the Pro tier this call sits in, so it adds
    # nothing to the bill.
    "places.addressComponents",
])
_DETAILS_FIELD_MASK = ",".join([
    "id", "displayName", "formattedAddress", "addressComponents", "location", "rating",
    "userRatingCount", "priceLevel", "businessStatus", "nationalPhoneNumber",
    "regularOpeningHours", "utcOffsetMinutes", "googleMapsUri", "photos",
])
_NOMINATIM = "https://nominatim.openstreetmap.org/search"


@dataclass
class GeocodeResult:
    name: str
    lat: float | None = None
    lng: float | None = None
    external_place_id: str | None = None
    address: str | None = None
    rating: float | None = None
    review_count: int | None = None
    price_level: int | None = None
    photos: list[str] = field(default_factory=list)
    hours: dict | None = None
    utc_offset_minutes: int | None = None
    phone: str | None = None
    business_status: str | None = None
    google_maps_url: str | None = None
    city: str | None = None
    region: str | None = None  # state/province short code, e.g. "TX", "NY"
    country: str | None = None
    # False when this came from the search call alone and still owes rating,
    # photos and hours. Nominatim results are never enriched either.
    enriched: bool = True


_PLACEHOLDER_NAMES = {"unknown", "n/a", "na", "unnamed", "unknown place", ""}


def _region_from_components(components: list[dict] | None) -> str | None:
    """State/province from Google's addressComponents ("TX", "NY", "ON")."""
    for c in components or []:
        if "administrative_area_level_1" in (c.get("types") or []):
            return c.get("shortText") or c.get("longText")
    return None


def region_from_address(address: str | None) -> str | None:
    """Last-resort region parse from a formatted address.

    "133 Duane St, New York, NY 10013, USA" -> "NY". Only accepts a 2-3 char
    uppercase code (optionally followed by a postal code), so verbose
    international addresses simply yield None rather than a wrong label.
    """
    if not address:
        return None
    parts = [p.strip() for p in address.split(",") if p.strip()]
    # Drop the trailing country, which is what precedes the state in most
    # "…, NY 10013, USA" formats.
    if len(parts) > 1 and parts[-1].replace(".", "").upper() in {
        "USA", "US", "UNITED STATES", "CANADA", "CA",
    }:
        parts.pop()
    if not parts:
        return None
    token = parts[-1].split()[0] if parts[-1].split() else ""
    if 2 <= len(token) <= 3 and token.isalpha() and token.isupper():
        return token
    return None


# Names that are one city wherever the geocoder or the model happens to split
# them. Keyed by the region they belong to, because several are ambiguous
# outside it — Manhattan is also a city in Kansas, and Brooklyn is a village in
# Ohio. A place with no region at all still resolves, on the reasoning that a
# food reel saying "Manhattan" means the island roughly always.
_CITY_ALIASES: dict[str | None, dict[str, str]] = {
    # Unambiguous anywhere.
    None: {
        "new york city": "New York",
        "nyc": "New York",
        "n.y.c.": "New York",
        "the bronx": "New York",
        "bronx": "New York",
        "staten island": "New York",
        "long island city": "New York",
    },
    # The five boroughs and the neighbourhoods geocoders most often return in
    # place of the city. All legally New York City.
    "NY": {
        "manhattan": "New York",
        "brooklyn": "New York",
        "queens": "New York",
        "astoria": "New York",
        "williamsburg": "New York",
        "bushwick": "New York",
        "greenpoint": "New York",
        "park slope": "New York",
        "dumbo": "New York",
        "red hook": "New York",
        "flushing": "New York",
        "jackson heights": "New York",
        "forest hills": "New York",
        "sunnyside": "New York",
        "harlem": "New York",
        "soho": "New York",
        "tribeca": "New York",
        "chelsea": "New York",
        "midtown": "New York",
        "downtown brooklyn": "New York",
        "greenwich village": "New York",
        "east village": "New York",
        "west village": "New York",
        "lower east side": "New York",
        "upper east side": "New York",
        "upper west side": "New York",
        "coney island": "New York",
    },
}


def normalize_city(name: str | None, region: str | None = None) -> str | None:
    """One city per city.

    The city on a place is whatever the model wrote or the geocoder returned,
    and both are inconsistent about the same place: New York arrived as "New
    York", "New York City", "NYC", "Manhattan", "Brooklyn" and "Long Island
    City", which became six separate city lists holding one map's worth of
    restaurants.

    Also strips a trailing region the model sometimes appends ("Austin, TX"),
    since the region is a column of its own and leaving it in the name makes
    "Austin" and "Austin, TX" two cities.
    """
    if not name:
        return None
    cleaned = " ".join(name.split()).strip(" ,")
    if not cleaned:
        return None

    # "Austin, TX" / "Paris, France" — keep only the leading locality.
    head = cleaned.split(",")[0].strip()
    if head:
        cleaned = head

    key = cleaned.lower()
    for scope in (region, None):
        alias = _CITY_ALIASES.get(scope, {}).get(key)
        if alias:
            return alias
    return cleaned


def candidate_city_names(name: str | None) -> set[str]:
    """Every canonical city a raw name could belong to.

    Writes normalise the city knowing its region, so "Brooklyn" is stored as
    "New York". A later lookup has no region yet — that is the whole point of
    looking up before paying — so it has to consider both: the plain
    normalisation and anything the aliases map this name onto under any region.
    Without this the cache misses every borough, which for a New York-heavy app
    is most of it.
    """
    if not name:
        return set()
    plain = normalize_city(name)
    if not plain:
        return set()
    out = {plain}
    key = name.split(",")[0].strip().lower()
    for scope in _CITY_ALIASES.values():
        if key in scope:
            out.add(scope[key])
    return out


def is_real_place_name(name: str | None) -> bool:
    """False for placeholder names a model emits when it can't read a venue's
    name on-screen ('<UNKNOWN>', 'unknown', blank). Such names must never be
    geocoded — the string 'unknown' happily matches a random hamlet upstate."""
    if not name:
        return False
    n = name.strip().strip("<>").strip().lower()
    return bool(n) and n not in _PLACEHOLDER_NAMES and "unknown" not in n


def geocode(place, address_hint: str | None = None) -> GeocodeResult:
    """Always returns a GeocodeResult. lat/lng may be None if no match found.

    `address_hint` is a precise street address the platform attached to the post
    (e.g. TikTok's locationMeta). When present, we geocode it directly and trust
    the top hit — this avoids name-collision mispins (a "Café Luna" in the wrong
    borough) that plague venue-name-only lookups.
    """
    # An un-nameable place can't be pinned — never geocode a placeholder like
    # "<UNKNOWN>" (it matches garbage). Return it un-pinned.
    if not is_real_place_name(place.name):
        log.info("geocode: skipping un-nameable place %r", place.name)
        return GeocodeResult(name=place.name, city=getattr(place, "city", None),
                             country=getattr(place, "country", None))

    use_google = settings.geocoder == "google" and settings.google_places_api_key

    # A precise platform address: in Google mode we fold it into the query (so we
    # still get ratings/photos for the right place); in free mode we geocode it
    # directly via Nominatim.
    if address_hint and not use_google:
        precise = _nominatim_address(address_hint, place)
        if precise is not None:
            return precise

    if use_google:
        result = _google(place, address_hint)
    else:
        result = _nominatim(place)

    if result.lat is None:
        log.warning("geocode: no coordinates for %r — will save without map pin", place.name)
    return result


def _region_from_osm(top: dict) -> str | None:
    """State/province code from a Nominatim `addressdetails=1` payload.

    Prefers the ISO 3166-2 subdivision ("US-TX" -> "TX"); otherwise falls back
    to the state name only when it's already short enough to read as a code.
    """
    addr = top.get("address") or {}
    iso = addr.get("ISO3166-2-lvl4") or addr.get("ISO3166-2-lvl3")
    if iso and "-" in iso:
        return iso.split("-")[-1]
    state = addr.get("state") or addr.get("province")
    return state if state and len(state) <= 3 else None


def _nominatim_address(address: str, place) -> GeocodeResult | None:
    """Geocode a precise street address and trust the top hit. Returns None if
    Nominatim finds nothing (caller then falls back to name-based lookup)."""
    try:
        r = httpx.get(
            _NOMINATIM,
            params={"q": address, "format": "json", "limit": 1, "addressdetails": 1},
            headers={"User-Agent": "ReelMap/0.1 (dev)"},
            timeout=30,
        )
        r.raise_for_status()
        results = r.json()
    except Exception:  # noqa: BLE001
        log.warning("nominatim address lookup failed for %r", address, exc_info=True)
        return None
    if not results:
        return None
    top = results[0]
    return GeocodeResult(
        external_place_id=f"osm:{top.get('osm_type','')}/{top.get('osm_id','')}",
        name=place.name,
        lat=float(top["lat"]),
        lng=float(top["lon"]),
        address=address,  # keep the clean platform address, not OSM's verbose one
        city=place.city,
        region=_region_from_osm(top) or region_from_address(address),
        country=getattr(place, "country", None),
    )


def _google_query(place, address_hint: str | None = None) -> str:
    """Best text query for Places search. A precise address (TikTok locationMeta)
    pins the exact venue; otherwise fall back to name + neighborhood + city, or
    the @handle when there's no clean name."""
    if address_hint:
        return f"{place.name}, {address_hint}"
    base = place.name
    if place.instagram_handle and not is_real_place_name(place.name):
        base = place.instagram_handle.replace("_", " ").replace(".", " ")
    parts = [base, place.neighborhood, place.city, getattr(place, "country", None)]
    return ", ".join(p for p in parts if p)


# Map our AI categories onto Google place types for the category-match score.
_CATEGORY_TYPES = {
    "cafe": {"cafe", "coffee_shop"},
    "restaurant": {"restaurant", "meal_takeaway", "meal_delivery", "brunch_restaurant", "breakfast_restaurant"},
    "bar": {"bar", "pub", "wine_bar"},
    "club": {"night_club"},
    "hotel": {"lodging", "hotel", "resort_hotel"},
    "sight": {"tourist_attraction", "museum", "park", "art_gallery", "landmark"},
    "event": {"event_venue", "performing_arts_theater"},
}
_GENERIC_TYPES = {"food", "point_of_interest", "establishment", "store"}


def _norm_join(text: str | None) -> str:
    return " ".join(
        t for t in "".join(ch.lower() if ch.isalnum() else " " for ch in (text or "")).split()
    )


def match_key(text: str | None) -> str:
    """Comparison form of a venue or city name — case, punctuation and spacing
    removed. The one place that decides what "the same name" means, so the cache
    lookup and the candidate scorer can't disagree about it."""
    return _norm_join(text)


def name_similarity(a: str | None, b: str | None) -> float:
    """0..1 similarity between two venue names, on the same normalisation the
    Google candidate scorer uses."""
    return difflib.SequenceMatcher(None, match_key(a), match_key(b)).ratio()


def _score_candidate(place, cand: dict) -> float:
    """Weighted match score in [0,1]. Protects against Google's top result being
    the wrong venue/branch: name similarity + locality + category + neighborhood.
    """
    disp = (cand.get("displayName") or {}).get("text") or ""
    addr = (cand.get("formattedAddress") or "").lower()
    types = set(cand.get("types") or [])
    if cand.get("primaryType"):
        types.add(cand["primaryType"])

    # name (0.40) — sequence ratio against the display name, best of name/handle
    name_score = difflib.SequenceMatcher(None, _norm_join(place.name), _norm_join(disp)).ratio()
    if place.instagram_handle:
        h = _norm_join(place.instagram_handle.replace("_", " ").replace(".", " "))
        name_score = max(name_score, difflib.SequenceMatcher(None, h, _norm_join(disp)).ratio())

    # locality (0.30) — is the candidate in the expected city / neighborhood?
    loc_score = 0.3
    if place.city and place.city.lower() in addr:
        loc_score = 0.8
    in_neighborhood = bool(place.neighborhood and place.neighborhood.lower() in addr)
    if in_neighborhood:
        loc_score = 1.0

    # category (0.15)
    want = _CATEGORY_TYPES.get(place.category, set())
    cat_score = 1.0 if (types & want) else (0.5 if (types & _GENERIC_TYPES) else 0.0)

    # branch/neighborhood (0.15) — the discriminator for chains with many locations
    branch_score = 1.0 if in_neighborhood else 0.5

    return 0.40 * name_score + 0.30 * loc_score + 0.15 * cat_score + 0.15 * branch_score


def _google(place, address_hint: str | None = None) -> GeocodeResult:
    unpinned = GeocodeResult(name=place.name, city=place.city, country=getattr(place, "country", None))
    candidates = _places_text_search(place, address_hint)
    if not candidates:
        return unpinned

    scored = sorted((( _score_candidate(place, c), c) for c in candidates),
                    key=lambda sc: sc[0], reverse=True)
    best_score, best = scored[0]
    second = scored[1][0] if len(scored) > 1 else 0.0

    if best_score < settings.place_min_score:
        log.info("google: best match for %r scored %.2f (< %.2f) — no pin",
                 place.name, best_score, settings.place_min_score)
        return unpinned

    confident = (best_score >= settings.place_auto_accept_threshold
                 and (best_score - second) >= settings.place_min_margin_over_second)
    log.info("google: %r -> %r score=%.2f margin=%.2f (%s)",
             place.name, (best.get("displayName") or {}).get("text"),
             best_score, best_score - second, "high" if confident else "medium")

    # The scorer above read only Text Search fields, so the decision is already
    # made. Place Details adds rating, photos and hours — things nobody sees
    # until they open the place — at the cost of a second billed call.
    if settings.lazy_place_enrichment:
        return _from_search_candidate(best, place)
    return _places_details(best["id"], place)


def _from_search_candidate(cand: dict, place) -> GeocodeResult:
    """A pinnable result built from the search hit alone.

    Everything needed to put the pin on the map and identify the venue again
    later. No rating, photos, hours, price or phone — those arrive when someone
    opens the place. `enriched=False` is what marks it as still owing that.
    """
    loc = cand.get("location") or {}
    lat, lng = loc.get("latitude"), loc.get("longitude")
    if lat is None or lng is None:
        return GeocodeResult(name=place.name, city=place.city,
                             country=getattr(place, "country", None))
    address = cand.get("formattedAddress")
    return GeocodeResult(
        external_place_id=f"gp:{cand['id']}",
        name=(cand.get("displayName") or {}).get("text") or place.name,
        lat=lat,
        lng=lng,
        address=address,
        business_status=cand.get("businessStatus"),
        city=place.city,
        region=_region_from_components(cand.get("addressComponents"))
        or region_from_address(address),
        country=getattr(place, "country", None),
        enriched=False,
    )


@dataclass
class _EnrichTarget:
    """The handful of fields _places_details reads off an extracted place."""

    name: str
    city: str | None = None
    country: str | None = None


def enrich(external_place_id: str, name: str, city: str | None = None,
           country: str | None = None) -> GeocodeResult | None:
    """Fetch rating, photos, hours and price for a place we already identified.

    The second of the two billed Google calls, split out so it can run when a
    person actually opens a place rather than for every pin at analysis time.
    Returns None when enrichment isn't possible or the call fails; the caller
    keeps whatever it already had.
    """
    if settings.geocoder != "google" or not settings.google_places_api_key:
        return None
    if not external_place_id or not external_place_id.startswith("gp:"):
        return None  # nominatim ids can't be enriched by Google

    result = _places_details(
        external_place_id.removeprefix("gp:"), _EnrichTarget(name, city, country)
    )
    return result if result.lat is not None else None


def _places_text_search(place, address_hint: str | None) -> list[dict]:
    try:
        r = httpx.post(
            _PLACES_TEXT,
            headers={
                "X-Goog-Api-Key": settings.google_places_api_key,
                "X-Goog-FieldMask": _TEXT_FIELD_MASK,
                "Content-Type": "application/json",
            },
            json={
                "textQuery": _google_query(place, address_hint),
                "regionCode": settings.google_places_region,
                "languageCode": settings.google_places_language,
                "maxResultCount": 5,
            },
            timeout=30,
        )
        r.raise_for_status()
        return r.json().get("places") or []
    except Exception:  # noqa: BLE001 - degrade to no pin
        log.warning("google text search failed for %r", place.name, exc_info=True)
        return []


_PRICE_LEVELS = {
    "PRICE_LEVEL_FREE": 0, "PRICE_LEVEL_INEXPENSIVE": 1, "PRICE_LEVEL_MODERATE": 2,
    "PRICE_LEVEL_EXPENSIVE": 3, "PRICE_LEVEL_VERY_EXPENSIVE": 4,
}


def _places_details(place_id: str, place) -> GeocodeResult:
    unpinned = GeocodeResult(name=place.name, city=place.city, country=getattr(place, "country", None))
    try:
        r = httpx.get(
            _PLACES_DETAILS.format(place_id=place_id),
            headers={
                "X-Goog-Api-Key": settings.google_places_api_key,
                "X-Goog-FieldMask": _DETAILS_FIELD_MASK,
            },
            timeout=30,
        )
        r.raise_for_status()
        d = r.json()
    except Exception:  # noqa: BLE001
        log.warning("google details failed for %s", place_id, exc_info=True)
        return unpinned

    loc = d.get("location") or {}
    lat, lng = loc.get("latitude"), loc.get("longitude")
    if lat is None or lng is None:
        return unpinned

    key = settings.google_places_api_key
    photos = [
        f"{_PLACES_MEDIA.format(photo_name=p['name'])}?maxWidthPx=800&key={key}"
        for p in (d.get("photos") or [])[:4]
        if p.get("name")
    ]
    address = d.get("formattedAddress")
    return GeocodeResult(
        external_place_id=f"gp:{d.get('id', place_id)}",
        name=(d.get("displayName") or {}).get("text") or place.name,
        lat=lat,
        lng=lng,
        address=address,
        rating=d.get("rating"),
        review_count=d.get("userRatingCount"),
        price_level=_PRICE_LEVELS.get(d.get("priceLevel")),
        photos=photos,
        hours=d.get("regularOpeningHours"),
        utc_offset_minutes=d.get("utcOffsetMinutes"),
        phone=d.get("nationalPhoneNumber"),
        business_status=d.get("businessStatus"),
        google_maps_url=d.get("googleMapsUri"),
        city=place.city,
        region=_region_from_components(d.get("addressComponents")) or region_from_address(address),
        country=getattr(place, "country", None),
    )


_STOPWORDS = {"the", "and", "cafe", "coffee", "restaurant", "bar", "hotel", "club", "house", "shop"}


def _name_tokens(text: str) -> set[str]:
    return {
        t for t in "".join(ch.lower() if ch.isalnum() else " " for ch in text).split()
        if len(t) >= 3 and t not in _STOPWORDS
    }


def _result_names_venue(place, display_name: str) -> bool:
    """A correct hit names the venue in its display_name. Without this check,
    Nominatim happily returns the city centroid for an unknown venue — a pin in
    the wrong spot, which is worse than no pin."""
    hay = _name_tokens(display_name)
    if _name_tokens(place.name) & hay:
        return True
    if place.instagram_handle:
        handle_words = place.instagram_handle.replace("_", " ").replace(".", " ")
        if _name_tokens(handle_words) & hay:
            return True
    return False


def _nominatim(place) -> GeocodeResult:
    # Nominatim matches readable names far better than run-together handles.
    # Try progressively simpler queries so a wrong neighborhood doesn't block a hit.
    n, nb, c, co = place.name, place.neighborhood, place.city, getattr(place, "country", None)
    handle_q = None
    if place.instagram_handle:
        handle_q = ", ".join(
            p for p in [
                place.instagram_handle.replace("_", " ").replace(".", " "),
                c, co,
            ] if p
        )

    candidates = list(dict.fromkeys(filter(None, [
        ", ".join(p for p in [n, nb, c, co] if p),   # full with neighborhood
        ", ".join(p for p in [n, c, co] if p),        # without neighborhood
        ", ".join(p for p in [n, co] if p),            # name + country only
        handle_q,                                       # handle-based fallback
    ])))

    for q in candidates:
        try:
            r = httpx.get(
                _NOMINATIM,
                params={"q": q, "format": "json", "limit": 3, "addressdetails": 1},
                headers={"User-Agent": "ReelMap/0.1 (dev)"},
                timeout=30,
            )
            r.raise_for_status()
            results = r.json()
        except Exception:  # noqa: BLE001 — one bad candidate must not kill the rest
            log.warning("nominatim query failed for %r", q, exc_info=True)
            continue

        for top in results:
            display = top.get("display_name") or ""
            if not _result_names_venue(place, display):
                continue  # matched only the city/street — wrong pin, keep looking
            return GeocodeResult(
                external_place_id=f"osm:{top.get('osm_type','')}/{top.get('osm_id','')}",
                name=place.name,
                lat=float(top["lat"]),
                lng=float(top["lon"]),
                address=display,
                city=place.city,
                region=_region_from_osm(top),
                country=getattr(place, "country", None),
            )

    # No verified match — return partial so the place is still saved (list-only, no pin)
    return GeocodeResult(name=place.name, city=place.city, country=getattr(place, "country", None))
