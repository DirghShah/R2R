"""Resolve an extracted place to real coordinates + enrichment.

Strategy: build the best text query we can (prefer the @handle, then
name + neighborhood + city), hit Google Places Text Search → Place Details for
coords, address, rating, photos, hours. Falls back to OpenStreetMap Nominatim
when no Google key is configured. Returns None when nothing matches (the caller
drops the place rather than pinning a wrong location).
"""
from __future__ import annotations

from dataclasses import dataclass

import httpx

from app.config import settings

_GOOGLE_TEXT = "https://maps.googleapis.com/maps/api/place/textsearch/json"
_GOOGLE_DETAILS = "https://maps.googleapis.com/maps/api/place/details/json"
_GOOGLE_PHOTO = "https://maps.googleapis.com/maps/api/place/photo"
_NOMINATIM = "https://nominatim.openstreetmap.org/search"


@dataclass
class GeocodeResult:
    external_place_id: str | None
    name: str
    lat: float
    lng: float
    address: str | None = None
    rating: float | None = None
    price_level: int | None = None
    photos: list[str] | None = None
    hours: dict | None = None
    city: str | None = None
    country: str | None = None


def build_query(place) -> str:
    """Best text query for a Place (from worker.extract)."""
    if place.instagram_handle:
        base = place.instagram_handle.replace("_", " ").replace(".", " ")
    else:
        base = place.name
    parts = [base, place.neighborhood, place.city, place.country]
    return ", ".join(p for p in parts if p)


def geocode(place) -> GeocodeResult | None:
    query = build_query(place)
    if settings.geocoder == "google" and settings.google_places_api_key:
        return _google(query)
    return _nominatim(query, place)


def _google(query: str) -> GeocodeResult | None:
    key = settings.google_places_api_key
    r = httpx.get(_GOOGLE_TEXT, params={"query": query, "key": key}, timeout=30)
    r.raise_for_status()
    results = r.json().get("results") or []
    if not results:
        return None
    top = results[0]
    place_id = top.get("place_id")

    details = {}
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
        return None

    photos = [
        f"{_GOOGLE_PHOTO}?maxwidth=800&photo_reference={p['photo_reference']}&key={key}"
        for p in (details.get("photos") or [])[:4]
        if p.get("photo_reference")
    ]
    return GeocodeResult(
        external_place_id=place_id,
        name=details.get("name") or top.get("name"),
        lat=loc["lat"],
        lng=loc["lng"],
        address=details.get("formatted_address") or top.get("formatted_address"),
        rating=details.get("rating"),
        price_level=details.get("price_level"),
        photos=photos or None,
        hours=details.get("opening_hours"),
    )


def _nominatim(query: str, place) -> GeocodeResult | None:
    r = httpx.get(
        _NOMINATIM,
        params={"q": query, "format": "json", "limit": 1},
        headers={"User-Agent": "ReelMap/0.1 (dev)"},
        timeout=30,
    )
    r.raise_for_status()
    results = r.json()
    if not results:
        return None
    top = results[0]
    return GeocodeResult(
        external_place_id=f"osm:{top.get('osm_type','')}/{top.get('osm_id','')}",
        name=place.name,
        lat=float(top["lat"]),
        lng=float(top["lon"]),
        address=top.get("display_name"),
        city=place.city,
        country=place.country,
    )
