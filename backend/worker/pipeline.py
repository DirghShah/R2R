"""The async analysis job: reel -> signals -> Claude -> geocode -> pins.

`analyze_reel` is the RQ task. It is idempotent on the reel's canonical_id: a
reel already analyzed is not re-run; its canonical Places are simply linked to
the new user (the reel-derived context is copied from a prior UserPlace).
"""
from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import select

from app.db import session
from app.models import City, Collection, Place, ReelSource, UserPlace
from worker import extract, frames, geocode, push
from worker.fetchers import get_fetcher

_CATEGORY_TITLES = {
    "cafe": "cafes", "restaurant": "restaurants", "hotel": "hotels",
    "bar": "bars", "club": "nightlife", "sight": "sightseeing",
    "event": "events", "other": "saved places",
}


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

        try:
            count = _run_analysis(db, reel, user_id)
            reel.status = "done"
            reel.analyzed_at = datetime.now(timezone.utc)
            db.commit()
        except Exception as exc:  # noqa: BLE001 - record failure, don't crash worker
            reel.status = "failed"
            reel.error = str(exc)[:500]
            db.commit()
            return {"status": "failed", "error": reel.error}

        _notify(user_id, count, reel)
        return {"status": "done", "places": count}
    finally:
        db.close()


def _run_analysis(db, reel: ReelSource, user_id: str) -> int:
    data = get_fetcher().fetch(reel.url)
    reel.caption = data.caption
    reel.author_handle = data.author_handle
    reel.thumbnail_url = data.thumbnail_url

    # Transient media: sample frames + transcribe, then it's gone (no storage).
    sampled = frames.sample_frames(data.video_url)
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
    )
    reel.summary = result.overall_summary

    saved = 0
    for ep in result.places:
        geo = geocode.geocode(ep)
        if geo is None:
            continue  # don't pin a place we can't locate
        place = _upsert_place(db, ep, geo)
        _upsert_user_place(db, user_id, place, reel, ep)
        _bucket_collection(db, user_id, place)
        saved += 1
    return saved


def _upsert_place(db, ep, geo) -> Place:
    city = _get_or_create_city(db, geo.city or ep.city, geo.country or ep.country)
    place = None
    if geo.external_place_id:
        place = db.scalar(select(Place).where(Place.external_place_id == geo.external_place_id))
    if place is None:
        place = Place(external_place_id=geo.external_place_id, name=geo.name)
        db.add(place)
    place.name = geo.name or ep.name
    place.category = ep.category
    place.lat, place.lng = geo.lat, geo.lng
    place.address = geo.address
    place.rating = geo.rating
    place.price_level = geo.price_level
    place.photos = geo.photos
    place.hours = geo.hours
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
        tips=ep.tips,
        what_to_order=ep.what_to_order,
        sources=ep.sources,
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
