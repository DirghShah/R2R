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
from app.schemas import (
    AddPlaceRequest,
    CollectionOut,
    PlaceSuggestion,
    ReelMention,
    SetPlaceLocationRequest,
    UserPlaceOut,
    VibeSearchMatch,
    VibeSearchRequest,
    VibeSearchResponse,
)
from app.maps import personal_map
from app.ratelimit import limit_place_search, limit_vibe_search
from worker import geocode, vibe_search
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

    rows = [up for up in db.scalars(stmt).unique() if up.user_id not in hidden]

    # One query for every place's reel lineage rather than one per row. The
    # detail screen renders from this response, so the mentions have to travel
    # with it — and a place a whole map shares would otherwise be N+1.
    mentions = _reel_mentions_bulk(db, {up.place_id for up in rows})

    out = []
    for up in rows:
        item = _to_out(up)
        item.seen_in_reels = [
            m for m in mentions.get(up.place_id, [])
            if not up.reel_source or m.url != up.reel_source.url
        ][:2]
        out.append(item)
    return out


def _reel_mentions_bulk(db: Session, place_ids: set[str]) -> dict[str, list[ReelMention]]:
    """Reels mentioning each of these places, keyed by place id."""
    if not place_ids:
        return {}
    rows = db.execute(
        select(UserPlace.place_id, ReelSource.url, ReelSource.author_handle,
               ReelSource.platform)
        .join(ReelSource, UserPlace.reel_source_id == ReelSource.id)
        .where(UserPlace.place_id.in_(place_ids), ReelSource.status == "done")
        .distinct()
    ).all()
    out: dict[str, list[ReelMention]] = {}
    for place_id, url, handle, platform in rows:
        bucket = out.setdefault(place_id, [])
        if any(m.url == url for m in bucket):
            continue
        bucket.append(ReelMention(url=url, author_handle=handle, platform=platform))
    return out


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
        added_manually=up.reel_source_id is None,
        seen_in_reels=[],
    )


def _reel_mentions(db: Session, place_id: str, exclude_reel_id: str | None,
                   limit: int = 2) -> list[ReelMention]:
    """Public reels that talk about this place, from anyone's analysis.

    Why a place someone merely searched for can arrive already knowing what to
    order: the canonical place row is shared, so every reel anybody has
    analysed about that venue is reachable from it. Every reel anyone adds
    therefore makes search better for everyone after them.

    Only the reel's own author is named. Which Nosh user saved it is nobody
    else's business and is never returned.
    """
    rows = db.execute(
        select(ReelSource.url, ReelSource.author_handle, ReelSource.platform)
        .join(UserPlace, UserPlace.reel_source_id == ReelSource.id)
        .where(
            UserPlace.place_id == place_id,
            ReelSource.id != (exclude_reel_id or ""),
            ReelSource.status == "done",
        )
        .distinct()
        .limit(limit)
    ).all()
    return [
        ReelMention(url=url, author_handle=handle, platform=platform)
        for url, handle, platform in rows
    ]


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
        return _with_mentions(db, up)

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
        return _with_mentions(db, up)

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
    return _with_mentions(db, up)


def _enrichment_is_fresh(place: Place) -> bool:
    """Enriched, and recently enough to trust the opening hours."""
    if place.enriched_at is None:
        return False
    seen = place.enriched_at
    if seen.tzinfo is None:  # SQLite hands back naive datetimes
        seen = seen.replace(tzinfo=timezone.utc)
    age = datetime.now(timezone.utc) - seen
    return age < timedelta(days=settings.place_enrichment_stale_days)


@router.post("/places/search", response_model=VibeSearchResponse)
def search_places_by_vibe(
    body: VibeSearchRequest,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> VibeSearchResponse:
    """Find saved places by what they feel like rather than what they're called.

    The app filters by name as you type, instantly and offline. This is the
    other half — "somewhere quiet I can work", "impressive but not stuffy" —
    which is compositional and needs something that can read the descriptions
    rather than index them.

    Scoped to one map by default. That is what people mean when they search
    while looking at a map, and it also keeps the prompt small, since every
    candidate place is part of the input.
    """
    limit_vibe_search(user.id)

    if body.map_id:
        require_member(db, body.map_id, user.id)
        map_ids = [body.map_id]
    else:
        map_ids = member_map_ids(db, user.id)
    if not map_ids:
        return VibeSearchResponse(query=body.query, matches=[], considered=0)

    hidden = blocked_ids(db, user.id)
    rows = db.scalars(
        select(UserPlace)
        .options(joinedload(UserPlace.place).joinedload(Place.city))
        .where(UserPlace.map_id.in_(map_ids))
        .order_by(UserPlace.saved_at.desc())
        .limit(settings.vibe_search_max_places)
    ).unique().all()

    candidates = [
        _catalogue_entry(up) for up in rows
        if up.place is not None and up.user_id not in hidden
    ]
    if not candidates:
        return VibeSearchResponse(query=body.query, matches=[], considered=0)

    try:
        result = vibe_search.search(body.query, candidates)
    except Exception:  # noqa: BLE001
        # Search failing should not look like "you have no places". The app
        # falls back to its own name filter on an error.
        raise HTTPException(
            status_code=503,
            detail="Couldn't run that search just now. Try again in a moment.",
        )

    return VibeSearchResponse(
        query=body.query,
        matches=[VibeSearchMatch(place_id=m.place_id, reason=m.reason)
                 for m in result.matches],
        considered=len(candidates),
    )


def _catalogue_entry(up: UserPlace) -> dict:
    """What the model gets to see about one saved place.

    Trimmed deliberately: the description is the richest signal and also the
    longest, and this is multiplied by every place a person has saved.
    """
    place = up.place
    description = (up.description or "").strip()
    return {
        "id": up.id,
        "name": place.name,
        "cuisine": place.cuisine,
        "category": place.category,
        "city": place.city.name if place.city else up.city,
        "vibes": up.vibe or [],
        "price_level": place.price_level or up.price_level_ai,
        "rating": place.rating,
        "description": description[:220] if description else None,
    }


# --- adding a place by searching for it -----------------------------------


@router.get("/places/suggest", response_model=list[PlaceSuggestion])
def suggest_places(
    q: str,
    lat: float | None = None,
    lng: float | None = None,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> list[PlaceSuggestion]:
    """Live suggestions while someone types a restaurant name.

    The first thing a new person does is add a place they have already been to,
    before they have shared anything — so this has to exist for the app to be
    worth opening on day one.

    Autocomplete, not a full text search: a tenth of a cent a call against
    three cents, which is what makes results-while-typing affordable rather
    than a charge on typing speed. The chosen place is resolved once, after.
    """
    limit_place_search(user.id)
    hits = geocode.suggest(q, lat=lat, lng=lng)
    return [
        PlaceSuggestion(place_id=h.place_id, name=h.name, detail=h.detail)
        for h in hits
    ]


@router.post("/places/add", response_model=UserPlaceOut, status_code=201)
def add_place_manually(
    body: AddPlaceRequest,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> UserPlaceOut:
    """Save a place the user picked from search.

    The resulting pin is an ordinary place: same canonical row, same
    enrichment, same map. What it lacks is a reel behind it — and if anybody
    else has ever shared a reel about this venue, it inherits what that reel
    said, so a searched place is not a poorer version of a shared one.
    """
    target_map = (
        require_member(db, body.map_id, user.id) if body.map_id
        else personal_map(db, user.id)
    )

    place = db.scalar(
        select(Place).where(Place.external_place_id == f"gp:{body.place_id}")
    )
    if place is None:
        data = geocode.resolve(body.place_id)
        if data is None:
            raise HTTPException(
                status_code=404,
                detail="Couldn't look that place up. Try picking it again.",
            )
        place = _place_from_geocode(db, data)

    existing = db.scalar(
        select(UserPlace).where(
            UserPlace.map_id == target_map.id, UserPlace.place_id == place.id
        )
    )
    if existing is not None:
        # Already pinned here. Not an error — the person asked for it to be on
        # this map, and it is.
        db.commit()
        return _with_mentions(db, existing)

    inherited = _inherited_context(db, place.id)
    up = UserPlace(
        map_id=target_map.id,
        user_id=user.id,
        place_id=place.id,
        reel_source_id=None,
        description=inherited.get("description"),
        tips=inherited.get("tips") or [],
        what_to_order=inherited.get("what_to_order") or [],
        vibe=inherited.get("vibe") or [],
    )
    db.add(up)
    db.commit()
    db.refresh(up)
    return _with_mentions(db, up)


def _with_mentions(db: Session, up: UserPlace) -> UserPlaceOut:
    out = _to_out(up)
    out.seen_in_reels = _reel_mentions(db, up.place_id, up.reel_source_id)
    return out


def _place_from_geocode(db: Session, data) -> Place:
    """Create the canonical place row from a resolved lookup."""
    from worker.geocode import normalize_city

    city = None
    city_name = normalize_city(data.city, data.region)
    if city_name:
        city = db.scalar(
            select(City).where(City.name == city_name, City.country == data.country)
        )
        if city is None:
            city = City(name=city_name, country=data.country)
            db.add(city)
            db.flush()

    place = Place(
        external_place_id=data.external_place_id,
        name=data.name,
        # Searched places have no AI category; the map colours by cuisine
        # first and falls back to this, and "restaurant" is the honest default
        # for something a person looked up by name.
        category="restaurant",
        lat=data.lat,
        lng=data.lng,
        address=data.address,
        region=data.region,
        rating=data.rating,
        review_count=data.review_count,
        price_level=data.price_level,
        photos=data.photos or None,
        hours=data.hours,
        utc_offset_minutes=data.utc_offset_minutes,
        phone=data.phone,
        business_status=data.business_status,
        google_maps_url=data.google_maps_url,
        city_id=city.id if city else None,
        last_verified_at=datetime.now(timezone.utc),
        enriched_at=datetime.now(timezone.utc) if data.enriched else None,
    )
    db.add(place)
    db.flush()
    return place


def _inherited_context(db: Session, place_id: str) -> dict:
    """What earlier reels said about this place, for a pin that has none.

    This is the whole reason searching is worth doing inside Nosh rather than
    in Maps: the tips and what-to-order came out of public reels somebody
    already analysed, so a place you looked up can arrive knowing things.

    Takes the most recent reel-sourced save that actually has content. Merging
    several would read as a committee wrote it.
    """
    row = db.scalars(
        select(UserPlace)
        .where(
            UserPlace.place_id == place_id,
            UserPlace.reel_source_id.isnot(None),
            UserPlace.description.isnot(None),
        )
        .order_by(UserPlace.saved_at.desc())
        .limit(1)
    ).first()
    if row is None:
        return {}
    return {
        "description": row.description,
        "tips": row.tips,
        "what_to_order": row.what_to_order,
        "vibe": row.vibe,
    }
