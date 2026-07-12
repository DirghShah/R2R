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

import logging
from dataclasses import dataclass, field

import httpx

from app.config import settings

log = logging.getLogger(__name__)

_GOOGLE_TEXT = "https://maps.googleapis.com/maps/api/place/textsearch/json"
_GOOGLE_DETAILS = "https://maps.googleapis.com/maps/api/place/details/json"
_GOOGLE_PHOTO = "https://maps.googleapis.com/maps/api/place/photo"
_NOMINATIM = "https://nominatim.openstreetmap.org/search"


@dataclass
class GeocodeResult:
    name: str
    lat: float | None = None
    lng: float | None = None
    external_place_id: str | None = None
    address: str | None = None
    rating: float | None = None
    price_level: int | None = None
    photos: list[str] = field(default_factory=list)
    hours: dict | None = None
    city: str | None = None
    country: str | None = None


def geocode(place) -> GeocodeResult:
    """Always returns a GeocodeResult. lat/lng may be None if no match found."""
    if settings.geocoder == "google" and settings.google_places_api_key:
        result = _google(place)
    else:
        result = _nominatim(place)

    if result.lat is None:
        log.warning("geocode: no coordinates for %r — will save without map pin", place.name)
    return result


def _google_query(place) -> str:
    """For Google: the @handle (un-slugged) is a strong search signal."""
    if place.instagram_handle:
        base = place.instagram_handle.replace("_", " ").replace(".", " ")
    else:
        base = place.name
    parts = [base, place.neighborhood, place.city, getattr(place, "country", None)]
    return ", ".join(p for p in parts if p)


def _google(place) -> GeocodeResult:
    key = settings.google_places_api_key
    query = _google_query(place)
    r = httpx.get(_GOOGLE_TEXT, params={"query": query, "key": key}, timeout=30)
    r.raise_for_status()
    results = r.json().get("results") or []
    if not results:
        return GeocodeResult(name=place.name, city=place.city, country=getattr(place, "country", None))

    top = results[0]
    place_id = top.get("place_id")
    details: dict = {}
    if place_id:
        d = httpx.get(
            _GOOGLE_DETAILS,
            params={
                "place_id": place_id,
                "key": key,
                "fields": "name,formatted_address,geometry,rating,price_level,photos,opening_hours,address_components",
            },
            timeout=30,
        )
        d.raise_for_status()
        details = d.json().get("result") or {}

    loc = (details.get("geometry") or top.get("geometry") or {}).get("location") or {}
    if "lat" not in loc:
        return GeocodeResult(name=place.name, city=place.city, country=getattr(place, "country", None))

    photos = [
        f"{_GOOGLE_PHOTO}?maxwidth=800&photo_reference={p['photo_reference']}&key={key}"
        for p in (details.get("photos") or [])[:4]
        if p.get("photo_reference")
    ]
    return GeocodeResult(
        external_place_id=place_id,
        name=details.get("name") or top.get("name") or place.name,
        lat=loc["lat"],
        lng=loc["lng"],
        address=details.get("formatted_address") or top.get("formatted_address"),
        rating=details.get("rating"),
        price_level=details.get("price_level"),
        photos=photos,
        hours=details.get("opening_hours"),
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
                params={"q": q, "format": "json", "limit": 3},
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
                country=getattr(place, "country", None),
            )

    # No verified match — return partial so the place is still saved (list-only, no pin)
    return GeocodeResult(name=place.name, city=place.city, country=getattr(place, "country", None))
