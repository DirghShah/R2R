"""The async analysis job: reel -> signals -> Claude -> geocode -> pins.

`analyze_reel` is the RQ task. It is idempotent on the reel's canonical_id: a
reel already analyzed is not re-run; its canonical Places are simply linked to
the new user (the reel-derived context is copied from a prior UserPlace).
"""
from __future__ import annotations

import logging
import time
from datetime import datetime, timezone

from sqlalchemy import select

from app.config import settings
from app.db import session
from app.models import City, Collection, Place, ReelSource, UserPlace
from worker import extract, frames, geocode, push
from worker.fetchers import get_fetcher

log = logging.getLogger(__name__)

_CATEGORY_TITLES = {
    "cafe": "cafes", "restaurant": "restaurants", "hotel": "hotels",
    "bar": "bars", "club": "nightlife", "sight": "sightseeing",
    "event": "events", "other": "saved places",
}

# Claude pricing per 1M tokens (input, output). Keep in sync with the model in use.
_CLAUDE_PRICES = {
    "claude-haiku-4-5": (1.0, 5.0),
    "claude-sonnet-4-6": (3.0, 15.0),
    "claude-opus-4-8": (5.0, 25.0),
}


def _claude_cost(model: str, in_tokens: int, out_tokens: int) -> float:
    p_in, p_out = _CLAUDE_PRICES.get(model, _CLAUDE_PRICES["claude-opus-4-8"])
    return in_tokens / 1_000_000 * p_in + out_tokens / 1_000_000 * p_out


def _log_metrics(reel: ReelSource, count: int, seconds: float,
                 in_tok: int, out_tok: int) -> dict:
    claude_cost = _claude_cost(settings.anthropic_model, in_tok, out_tok)
    apify_cost = settings.apify_cost_per_reel if settings.reel_fetcher == "apify" else 0.0
    # Geocoding: nominatim is free; google bills per accepted place (Text Search
    # Pro + one Place Details Enterprise) — see settings.google_cost_per_place.
    geo_cost = 0.0 if settings.geocoder == "nominatim" else round(settings.google_cost_per_place * count, 4)
    total = claude_cost + apify_cost + geo_cost
    summary = {
        "reel": reel.canonical_id,
        "places": count,
        "duration_s": round(seconds, 1),
        "claude_model": settings.anthropic_model,
        "claude_in_tokens": in_tok,
        "claude_out_tokens": out_tok,
        "claude_cost_usd": round(claude_cost, 4),
        "apify_cost_usd": round(apify_cost, 4),
        "geocode_cost_usd": geo_cost,
        "total_cost_usd": round(total, 4),
    }
    # print() guarantees visibility in `docker compose logs worker`.
    print(f"[metrics] {summary}", flush=True)
    log.info("analyze_reel metrics: %s", summary)
    return summary


def analyze_reel(reel_id: str, user_id: str) -> dict:
    db = session()
    try:
        reel = db.get(ReelSource, reel_id)
        if reel is None:
            return {"error": "reel not found"}

        if reel.status == "done":
            count = _link_existing_to_user(db, reel, user_id)
            db.commit()
            return {"status": "done", "places": count, "cached": True}

        reel.status = "processing"
        db.commit()

        started = time.monotonic()
        try:
            count, in_tok, out_tok = _run_analysis(db, reel, user_id)
            reel.status = "done"
            reel.analyzed_at = datetime.now(timezone.utc)
            db.commit()
        except Exception as exc:  # noqa: BLE001 - record failure, don't crash worker
            reel.status = "failed"
            reel.error = str(exc)[:500]
            db.commit()
            print(f"[metrics] analyze FAILED reel={reel.canonical_id} error={reel.error}", flush=True)
            return {"status": "failed", "error": reel.error}

        metrics = _log_metrics(reel, count, time.monotonic() - started, in_tok, out_tok)
        _notify(user_id, count, reel)
        return {"status": "done", "places": count, "metrics": metrics}
    finally:
        db.close()


def _run_analysis(db, reel: ReelSource, user_id: str) -> tuple[int, int, int]:
    data = get_fetcher(reel.platform).fetch(reel.url)
    reel.caption = data.caption
    reel.author_handle = data.author_handle
    reel.thumbnail_url = data.thumbnail_url

    # Transient media: sample frames + transcribe, then it's gone (no storage).
    # Pass the reel page URL so frames.sample_frames can fall back to yt-dlp when
    # the fetcher has no usable direct media URL. Skip the page fallback for the
    # offline stub (its URL is a placeholder, not a real reel).
    page_url = data.url if settings.reel_fetcher != "stub" else None
    sampled = frames.sample_frames(data.video_url, page_url=page_url)
    transcript = None
    if data.video_url:
        from worker import transcribe as _t  # deferred (heavy whisper import)

        transcript = _t.transcribe(data.video_url)
    reel.transcript = transcript

    result = extract.extract_places(
        caption=data.caption,
        transcript=transcript,
        at_handles=data.at_handles,
        tagged_location=data.tagged_location,
        hashtags=data.hashtags,
        frames=sampled,
        author_handle=data.author_handle,
        tagged_address=data.tagged_address,
    )
    reel.summary = result.extraction.overall_summary

    # Drop places the model saw on-screen but couldn't name ("<UNKNOWN>") — they
    # can't be pinned or looked up and only render as garbage in the app.
    all_places = result.extraction.places
    places = [ep for ep in all_places if geocode.is_real_place_name(ep.name)]
    if len(places) < len(all_places):
        log.info("reel %s: dropped %d un-nameable place(s)",
                 reel.canonical_id, len(all_places) - len(places))

    # A precise platform address describes the reel's single tagged venue — only
    # trust it to pin when the reel is about one place (not a "10 cafes" list).
    single_venue_address = data.tagged_address if len(places) == 1 else None

    saved = 0
    for ep in places:
        # Inherit the reel-level city/country when a place doesn't name its own —
        # a "9 cafes in Dallas" reel rarely repeats the city per item.
        ep.city = ep.city or result.extraction.primary_city
        ep.country = ep.country or result.extraction.primary_country

        # One flaky geocoding call must never fail the whole reel: fall back to
        # an un-pinned place (still listed) and keep going.
        try:
            geo = geocode.geocode(ep, address_hint=single_venue_address)
        except Exception:  # noqa: BLE001
            log.warning("geocode raised for %r — saving without a pin", ep.name, exc_info=True)
            geo = geocode.GeocodeResult(name=ep.name, city=ep.city, country=ep.country)

        place = _upsert_place(db, ep, geo)
        _upsert_user_place(db, user_id, place, reel, ep)
        _bucket_collection(db, user_id, place)
        saved += 1
    return saved, result.input_tokens, result.output_tokens


def _upsert_place(db, ep, geo) -> Place:
    city = _get_or_create_city(db, geo.city or ep.city, geo.country or ep.country)
    place = None
    if geo.external_place_id:
        place = db.scalar(select(Place).where(Place.external_place_id == geo.external_place_id))
    if place is None:
        place = Place(external_place_id=geo.external_place_id, name=geo.name or ep.name)
        db.add(place)
    place.name = geo.name or ep.name
    place.category = ep.category
    place.cuisine = ep.cuisine
    place.lat = geo.lat
    place.lng = geo.lng
    place.address = geo.address
    place.rating = geo.rating
    place.review_count = geo.review_count
    place.price_level = geo.price_level
    place.photos = geo.photos or None
    place.hours = geo.hours
    place.phone = geo.phone
    place.business_status = geo.business_status
    place.google_maps_url = geo.google_maps_url
    place.last_verified_at = datetime.now(timezone.utc)
    place.city = city
    db.flush()
    return place


def _upsert_user_place(db, user_id: str, place: Place, reel: ReelSource, ep) -> UserPlace:
    existing = db.scalar(
        select(UserPlace).where(
            UserPlace.user_id == user_id,
            UserPlace.place_id == place.id,
            UserPlace.reel_source_id == reel.id,
        )
    )
    if existing:
        return existing
    up = UserPlace(
        user_id=user_id,
        place_id=place.id,
        reel_source_id=reel.id,
        description=ep.description,
        tips=ep.tips or [],
        what_to_order=ep.what_to_order or [],
        vibe=ep.vibe or [],
        instagram_handle=ep.instagram_handle,
        website=ep.website,
        hours_hint=ep.hours_hint,
        price_level_ai=ep.price_level,
        sources=[],
        confidence=ep.confidence,
    )
    db.add(up)
    db.flush()
    return up


def _bucket_collection(db, user_id: str, place: Place) -> None:
    coll = db.scalar(
        select(Collection).where(
            Collection.user_id == user_id,
            Collection.city_id == place.city_id,
            Collection.category == place.category,
        )
    )
    if coll is None:
        city_name = place.city.name if place.city else "Saved"
        title = f"{city_name} {_CATEGORY_TITLES.get(place.category, 'saved places')}"
        coll = Collection(
            user_id=user_id, city_id=place.city_id, category=place.category, title=title
        )
        db.add(coll)


def _get_or_create_city(db, name: str | None, country: str | None) -> City | None:
    if not name:
        return None
    city = db.scalar(select(City).where(City.name == name, City.country == country))
    if city is None:
        city = City(name=name, country=country)
        db.add(city)
        db.flush()
    return city


def _link_existing_to_user(db, reel: ReelSource, user_id: str) -> int:
    """Cached reel: copy reel-derived UserPlaces from any prior user to this one."""
    template = db.scalars(
        select(UserPlace).where(UserPlace.reel_source_id == reel.id)
    ).all()
    seen_places: set[str] = set()
    count = 0
    for t in template:
        if t.user_id == user_id or t.place_id in seen_places:
            continue
        seen_places.add(t.place_id)
        already = db.scalar(
            select(UserPlace).where(
                UserPlace.user_id == user_id,
                UserPlace.place_id == t.place_id,
                UserPlace.reel_source_id == reel.id,
            )
        )
        if already:
            continue
        db.add(UserPlace(
            user_id=user_id, place_id=t.place_id, reel_source_id=reel.id,
            description=t.description, tips=t.tips, what_to_order=t.what_to_order,
            vibe=t.vibe, instagram_handle=t.instagram_handle, website=t.website,
            hours_hint=t.hours_hint, price_level_ai=t.price_level_ai,
            sources=t.sources, confidence=t.confidence,
        ))
        place = db.get(Place, t.place_id)
        if place:
            _bucket_collection(db, user_id, place)
        count += 1
    return count


def _notify(user_id: str, count: int, reel: ReelSource) -> None:
    if count <= 0:
        return
    push.notify_user(
        user_id,
        title="ReelMap",
        body=f"{count} place{'s' if count != 1 else ''} saved from your reel 📍",
        deep_link=f"reelmap://reels/{reel.id}",
    )
