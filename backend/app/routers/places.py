"""Read the user's saved places and auto-generated city lists."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException, Response
from sqlalchemy import func, select
from sqlalchemy.orm import Session, joinedload

from app.auth import get_current_user
from app.config import settings
from app.routers.moderation import blocked_ids
from app.db import get_db
from app.maps import member_map_ids, require_member
from app.models import City, Collection, Map, MapMember, Place, ReelSource, User, UserPlace
from app.schemas import CollectionOut, SetPlaceLocationRequest, UserPlaceOut
from worker import geocode
from worker.geocode import region_from_address

router = APIRouter(tags=["places"])


@router.get("/places", response_model=list[UserPlaceOut])
def list_places(
    city: str | None = None,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> list[UserPlaceOut]:
    # Every map the user belongs to, in one response, each row tagged with its
    # map_id — the client filters locally. Deliberately NOT filtered per map:
    # the iOS cache reconciles by deleting anything the server didn't return,
    # so a scoped response would silently wipe every other map's pins.
    map_ids = member_map_ids(db, user.id)
    if not map_ids:
        return []

    # Blocking means "stop showing me this person's contributions". Applied
    # here rather than at write time so unblocking restores everything.
    hidden = blocked_ids(db, user.id)

    stmt = (
        select(UserPlace)
        .options(
            joinedload(UserPlace.place),
            joinedload(UserPlace.reel_source),
            joinedload(UserPlace.user),
        )
        .where(UserPlace.map_id.in_(map_ids))
        .order_by(UserPlace.saved_at.desc())
    )
    if city:
        stmt = stmt.join(UserPlace.place).join(Place.city).where(City.name == city)

    return [_to_out(up) for up in db.scalars(stmt).unique()
            if up.user_id not in hidden]


def _to_out(up: UserPlace) -> UserPlaceOut:
    adder = up.user
    return UserPlaceOut(
        id=up.id,
        place=up.place,
        map_id=up.map_id,
        added_by_id=adder.id if adder else None,
        added_by_name=adder.display_name if adder else None,
        added_by_color=adder.avatar_color if adder else None,
        city=up.place.city.name if up.place and up.place.city else None,
        reel_url=up.reel_source.url if up.reel_source else None,
        description=up.description,
        tips=up.tips,
        what_to_order=up.what_to_order,
        vibe=up.vibe,
        instagram_handle=up.instagram_handle,
        website=up.website,
        hours_hint=up.hours_hint,
        price_level_ai=up.price_level_ai,
        confidence=up.confidence,
        saved_at=up.saved_at,
    )


@router.patch("/places/{user_place_id}/location", response_model=UserPlaceOut)
def set_place_location(
    user_place_id: str,
    body: SetPlaceLocationRequest,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> UserPlaceOut:
    """Drop the pin by hand for a place the geocoder couldn't resolve.

    Geocoding deliberately returns no coordinates rather than risk a wrong pin,
    which leaves the place listed but off the map. This is the escape hatch.
    """
    up = _member_place(db, user_place_id, user.id)
    if up.place is None:
        raise HTTPException(status_code=404, detail="Place not found")

    place = up.place
    place.lat = body.lat
    place.lng = body.lng
    place.location_source = "user"
    if body.address:
        place.address = body.address
        place.region = place.region or region_from_address(body.address)
    place.last_verified_at = datetime.now(timezone.utc)
    db.commit()
    db.refresh(up)
    return _to_out(up)


@router.delete("/places/{user_place_id}", status_code=204)
def delete_place(
    user_place_id: str,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> Response:
    """Remove one saved place (a wrong pin, a place you're not interested in).

    Only the user's own link to the place is deleted — the canonical Place row
    is shared with other users and with the cached reel analysis, so it stays.
    Re-submitting the reel will bring the pin back.
    """
    up = _member_place(db, user_place_id, user.id)

    city_id = up.place.city_id if up.place else None
    category = up.place.category if up.place else None
    db.delete(up)
    db.flush()
    _prune_empty_collection(db, user.id, city_id, category)
    db.commit()
    return Response(status_code=204)


def _member_place(db: Session, user_place_id: str, user_id: str) -> UserPlace:
    """A pin is manageable by anyone in its map, not only whoever added it —
    otherwise a shared map's members couldn't clean up each other's mistakes."""
    up = db.scalar(
        select(UserPlace)
        .join(MapMember, MapMember.map_id == UserPlace.map_id)
        .where(UserPlace.id == user_place_id, MapMember.user_id == user_id)
    )
    if up is None:
        raise HTTPException(status_code=404, detail="Place not found")
    return up


def _prune_empty_collection(db: Session, user_id: str, city_id: str | None, category: str | None) -> None:
    """Drop the auto-generated list once its last place is gone, so the user
    isn't left with an empty 'Dallas cafes'."""
    remaining = db.scalar(
        select(func.count())
        .select_from(UserPlace)
        .join(Place, Place.id == UserPlace.place_id)
        .where(UserPlace.user_id == user_id, Place.city_id == city_id, Place.category == category)
    )
    if remaining:
        return
    coll = db.scalar(
        select(Collection).where(
            Collection.user_id == user_id,
            Collection.city_id == city_id,
            Collection.category == category,
        )
    )
    if coll is not None:
        db.delete(coll)


@router.get("/lists", response_model=list[CollectionOut])
def list_collections(
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> list[CollectionOut]:
    collections = db.scalars(
        select(Collection).where(Collection.user_id == user.id)
    ).all()

    out: list[CollectionOut] = []
    for c in collections:
        count = db.scalar(
            select(func.count())
            .select_from(UserPlace)
            .join(Place, Place.id == UserPlace.place_id)
            .where(
                UserPlace.user_id == user.id,
                Place.city_id == c.city_id,
                Place.category == c.category,
            )
        )
        if not count:
            continue  # every place was deleted — don't show an empty list
        city = db.get(City, c.city_id) if c.city_id else None
        out.append(
            CollectionOut(
                id=c.id, title=c.title, category=c.category,
                city=city.name if city else None, place_count=count,
            )
        )
    return out


@router.post("/places/{user_place_id}/enrich", response_model=UserPlaceOut)
def enrich_place(
    user_place_id: str,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> UserPlaceOut:
    """Fetch this place's rating, photos and hours, if we don't have them fresh.

    Enrichment is the second of two billed lookups, and it buys nothing until a
    person is actually looking at the place — the scorer that decides *which*
    venue is right reads only the search response. So the app calls this when
    someone opens a place, and the cost follows attention instead of preceding
    it.

    Idempotent and cheap to call: a place enriched recently returns immediately
    without contacting anyone. Failures are silent by design — the caller
    already has a usable place and a missing rating is not worth an error.
    """
    up = _member_place(db, user_place_id, user.id)
    place = up.place
    if place is None:
        raise HTTPException(status_code=404, detail="Place not found")

    if _enrichment_is_fresh(place):
        return _to_out(up)

    data = geocode.enrich(
        place.external_place_id or "", place.name,
        city=place.city.name if place.city else None,
    )
    if data is None:
        # Nothing to add — a Nominatim pin, a dead id, or Google was down. Mark
        # the attempt so a place that can never be enriched isn't retried on
        # every single open.
        place.enriched_at = datetime.now(timezone.utc)
        db.commit()
        return _to_out(up)

    place.rating = data.rating
    place.review_count = data.review_count
    place.price_level = data.price_level
    place.photos = data.photos or None
    place.hours = data.hours
    place.utc_offset_minutes = data.utc_offset_minutes
    place.phone = data.phone
    place.business_status = data.business_status or place.business_status
    place.google_maps_url = data.google_maps_url or place.google_maps_url
    # A hand-placed pin outranks the geocoder here too: enrichment must never
    # move a location the user corrected.
    if place.location_source != "user" and data.address:
        place.address = data.address
        place.region = data.region or place.region
    place.enriched_at = datetime.now(timezone.utc)
    place.last_verified_at = place.enriched_at
    db.commit()
    db.refresh(up)
    return _to_out(up)


def _enrichment_is_fresh(place: Place) -> bool:
    """Enriched, and recently enough to trust the opening hours."""
    if place.enriched_at is None:
        return False
    seen = place.enriched_at
    if seen.tzinfo is None:  # SQLite hands back naive datetimes
        seen = seen.replace(tzinfo=timezone.utc)
    age = datetime.now(timezone.utc) - seen
    return age < timedelta(days=settings.place_enrichment_stale_days)
