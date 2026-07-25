"""Read the user's saved places and auto-generated city lists."""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Response
from sqlalchemy import func, select
from sqlalchemy.orm import Session, joinedload

from app.auth import get_current_user
from app.db import get_db
from app.models import City, Collection, Place, ReelSource, User, UserPlace
from app.schemas import CollectionOut, UserPlaceOut

router = APIRouter(tags=["places"])


@router.get("/places", response_model=list[UserPlaceOut])
def list_places(
    city: str | None = None,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> list[UserPlaceOut]:
    stmt = (
        select(UserPlace)
        .options(joinedload(UserPlace.place), joinedload(UserPlace.reel_source))
        .where(UserPlace.user_id == user.id)
        .order_by(UserPlace.saved_at.desc())
    )
    if city:
        stmt = stmt.join(UserPlace.place).join(Place.city).where(City.name == city)

    out: list[UserPlaceOut] = []
    for up in db.scalars(stmt).unique():
        out.append(
            UserPlaceOut(
                id=up.id,
                place=up.place,
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
        )
    return out


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
    up = db.scalar(
        select(UserPlace).where(UserPlace.id == user_place_id, UserPlace.user_id == user.id)
    )
    if up is None:
        raise HTTPException(status_code=404, detail="Place not found")

    city_id = up.place.city_id if up.place else None
    category = up.place.category if up.place else None
    db.delete(up)
    db.flush()
    _prune_empty_collection(db, user.id, city_id, category)
    db.commit()
    return Response(status_code=204)


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
