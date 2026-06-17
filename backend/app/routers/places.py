"""Read the user's saved places and auto-generated city lists."""
from __future__ import annotations

from fastapi import APIRouter, Depends
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
                confidence=up.confidence,
                saved_at=up.saved_at,
            )
        )
    return out


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
        city = db.get(City, c.city_id) if c.city_id else None
        out.append(
            CollectionOut(
                id=c.id, title=c.title, category=c.category,
                city=city.name if city else None, place_count=count or 0,
            )
        )
    return out
