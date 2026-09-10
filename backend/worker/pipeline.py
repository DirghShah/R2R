"""The async analysis job: reel -> signals -> Claude -> geocode -> pins.

`analyze_reel` is the RQ task. It is idempotent on the reel's canonical_id: a
reel already analyzed is not re-run; its canonical Places are simply linked to
the new user (the reel-derived context is copied from a prior UserPlace).
"""
from __future__ import annotations

import logging
import time
from datetime import datetime, timezone

from sqlalchemy import func, select

from app.config import settings
from app.db import session
from app.models import City, Collection, Place, ReelSource, User, UserPlace
from worker import extract, frames, geocode, push
from worker.fetchers import get_fetcher

log = logging.getLogger(__name__)


class UnsupportedReel(Exception):
    """The reel analysed fine — it just isn't something Nosh can pin.

    Distinct from a failure on purpose. A meal-kit ad isn't a bug in the
    pipeline, and telling the user "couldn't analyze that reel" would send them
    off retrying something that will never work. Its message is written to be
    shown to the user verbatim.

    Carries the token counts because a rejected reel still cost a fetch and a
    Claude call — the whole point of rejecting early is that it costs *less*,
    not nothing, and that saving is only visible if both are recorded.
    """

    def __init__(self, message: str, input_tokens: int = 0, output_tokens: int = 0) -> None:
        super().__init__(message)
        self.input_tokens = input_tokens
        self.output_tokens = output_tokens


# Keyed by `reel_kind` from the extractor. Written as user-facing copy: these
# strings land in the activity row and the push notification unchanged.
_UNSUPPORTED_REASONS = {
    "advertisement": "That looks like an ad, not a place you can visit. "
                     "Try a reel about a specific restaurant or café.",
    "recipe_or_cooking": "That's a recipe video — there's no venue to pin. "
                         "Try a reel about a restaurant or café.",
    "product_or_service": "That's a product or delivery service, not somewhere you can go. "
                          "Try a reel about a specific restaurant or café.",
    "not_places": "We couldn't find a restaurant or café in that reel.",
}

_CATEGORY_TITLES = {
    "cafe": "cafes", "restaurant": "restaurants", "hotel": "hotels",
    "bar": "bars", "club": "nightlife", "sight": "sightseeing",
    "event": "events", "other": "saved places",
}

# Claude pricing per 1M tokens (input, output). An unlisted model falls back to
# the most expensive entry on purpose: a cost report that under-reports is worse
# than one that over-reports, because nobody investigates a bill that looks fine.
_CLAUDE_PRICES = {
    "claude-opus-5": (5.0, 25.0),
    "claude-sonnet-5": (2.0, 10.0),
    "claude-haiku-4-5": (1.0, 5.0),
    # Previous generation, kept so historical reels still price correctly.
    "claude-opus-4-8": (5.0, 25.0),
    "claude-sonnet-4-6": (3.0, 15.0),
}

_FALLBACK_PRICE = max(_CLAUDE_PRICES.values())


def _claude_cost(model: str, in_tokens: int, out_tokens: int) -> float:
    p_in, p_out = _CLAUDE_PRICES.get(model, _FALLBACK_PRICE)
    return in_tokens / 1_000_000 * p_in + out_tokens / 1_000_000 * p_out


def _cost_detail(places: int, in_tok: int, out_tok: int) -> dict:
    """What a run cost and what it was made of.

    One place that knows the answer, used by the log line, the stored total and
    the stored breakdown, so the three can't drift apart. The vendor split and
    the inputs are kept because a single total can't be broken down later, and
    can't be re-priced when a vendor changes its rates.
    """
    claude = _claude_cost(settings.anthropic_model, in_tok, out_tok)
    apify = settings.apify_cost_per_reel if settings.reel_fetcher == "apify" else 0.0
    geo = 0.0 if settings.geocoder == "nominatim" else settings.google_cost_per_place * places
    return {
        "model": settings.anthropic_model,
        "fetcher": settings.reel_fetcher,
        "geocoder": settings.geocoder,
        "input_tokens": in_tok,
        "output_tokens": out_tok,
        "places": places,
        "claude_usd": round(claude, 6),
        "fetch_usd": round(apify, 6),
        "geocode_usd": round(geo, 6),
        "total_usd": round(claude + apify + geo, 6),
    }


def _total_cost(places: int, in_tok: int, out_tok: int) -> float:
    return round(_cost_detail(places, in_tok, out_tok)["total_usd"], 4)


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


def analyze_reel(reel_id: str, user_id: str, map_id: str | None = None) -> dict:
    """`map_id` is where the pins land; None means the submitter's personal map
    (kept optional so jobs enqueued before maps existed still run)."""
    db = session()
    try:
        reel = db.get(ReelSource, reel_id)
        if reel is None:
            return {"error": "reel not found"}

        target_map = map_id or _personal_map_id(db, user_id)

        if reel.status == "done":
            count = _link_existing_to_user(db, reel, user_id, target_map)
            db.commit()
            # Reusing a cached analysis still put new pins on this user's map —
            # they need telling just the same as a fresh run.
            if count > 0:
                _notify(user_id, count, reel)
                _notify_other_members(db, target_map, user_id, count)
            return {"status": "done", "places": count, "cached": True}

        reel.status = "processing"
        reel.started_at = datetime.now(timezone.utc)
        reel.error = None
        db.commit()

        started = time.monotonic()
        try:
            count, in_tok, out_tok = _run_analysis(db, reel, user_id, target_map)
            reel.status = "done"
            reel.analyzed_at = datetime.now(timezone.utc)
            reel.cost_detail = _cost_detail(count, in_tok, out_tok)
            reel.cost_usd = round(reel.cost_detail["total_usd"], 4)
            db.commit()
        except UnsupportedReel as exc:
            # Not a failure: the analysis worked and the answer was "there's
            # nothing here to pin". Kept as its own status so the app can say
            # why instead of showing a retryable error for something that will
            # never succeed.
            reel.status = "unsupported"
            reel.error = str(exc)[:500]
            reel.analyzed_at = datetime.now(timezone.utc)
            # No geocoding happened — that's the saving, and recording zero
            # places is what makes it measurable.
            reel.cost_detail = _cost_detail(0, exc.input_tokens, exc.output_tokens)
            reel.cost_usd = round(reel.cost_detail["total_usd"], 4)
            db.commit()
            print(f"[metrics] analyze SKIPPED reel={reel.canonical_id} reason={reel.error}", flush=True)
            _notify(user_id, 0, reel)
            return {"status": "unsupported", "reason": reel.error}
        except Exception as exc:  # noqa: BLE001 - record failure, don't crash worker
            reel.status = "failed"
            reel.error = str(exc)[:500]
            db.commit()
            print(f"[metrics] analyze FAILED reel={reel.canonical_id} error={reel.error}", flush=True)
            _notify(user_id, 0, reel)
            return {"status": "failed", "error": reel.error}

        metrics = _log_metrics(reel, count, time.monotonic() - started, in_tok, out_tok)
        _notify(user_id, count, reel)
        _notify_other_members(db, target_map, user_id, count)
        return {"status": "done", "places": count, "metrics": metrics}
    finally:
        db.close()


def _personal_map_id(db, user_id: str) -> str:
    from app.maps import personal_map

    m = personal_map(db, user_id)
    db.commit()
    return m.id


def _run_analysis(db, reel: ReelSource, user_id: str, map_id: str) -> tuple[int, int, int]:
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

    # Everything below the extraction call and above geocoding is free to reject
    # on: Claude has already told us what this reel is, and Google Places (~90%
    # of the marginal cost) hasn't been touched yet.
    kind = (result.extraction.reel_kind or "venue_recommendation").strip().lower()
    if kind != "venue_recommendation":
        raise UnsupportedReel(
            _UNSUPPORTED_REASONS.get(kind, _UNSUPPORTED_REASONS["not_places"]),
            result.input_tokens, result.output_tokens)

    # Drop places the model saw on-screen but couldn't name ("<UNKNOWN>") — they
    # can't be pinned or looked up and only render as garbage in the app.
    all_places = result.extraction.places
    places = [ep for ep in all_places if geocode.is_real_place_name(ep.name)]
    if len(places) < len(all_places):
        log.info("reel %s: dropped %d un-nameable place(s)",
                 reel.canonical_id, len(all_places) - len(places))

    # Coerce the cuisine onto the closed list. The extractor is asked for one
    # of these verbatim, but tool-use schemas are advisory rather than enforced,
    # so an off-list label would otherwise flow straight through to the map's
    # filter chips and pin colours — which is the mess this replaced.
    for ep in places:
        ep.cuisine = extract.normalize_cuisine(ep.cuisine)

    # Category filter. Done per-place rather than per-reel on purpose: a "best of
    # Dallas" reel with five cafes and one hotel should still save the cafes.
    allowed = settings.allowed_categories
    kept = [ep for ep in places if (ep.category or "").strip().lower() in allowed]
    if len(kept) < len(places):
        log.info("reel %s: dropped %d place(s) outside %s",
                 reel.canonical_id, len(places) - len(kept), sorted(allowed))
    places = kept

    if not places:
        raise UnsupportedReel(
            "We couldn't find any restaurants or cafés in that reel.",
            result.input_tokens, result.output_tokens)

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
        _, created = _upsert_user_place(db, user_id, place, reel, ep, map_id)
        _bucket_collection(db, user_id, place)
        if created:
            saved += 1
    return saved, result.input_tokens, result.output_tokens


def _upsert_place(db, ep, geo) -> Place:
    # Region first: it decides which city aliases apply, and it is also what
    # the pin ends up labelled with.
    region = geo.region or geocode.region_from_address(geo.address)
    city = _get_or_create_city(
        db, geo.city or ep.city, geo.country or ep.country, region=region
    )
    place = None
    if geo.external_place_id:
        place = db.scalar(select(Place).where(Place.external_place_id == geo.external_place_id))
    else:
        # Un-pinned places have no external id; match on name within the city so
        # a second reel about the same venue reuses the row instead of cloning it.
        name = (geo.name or ep.name).strip()
        place = db.scalar(
            select(Place).where(
                Place.external_place_id.is_(None),
                func.lower(Place.name) == name.lower(),
                Place.city_id == (city.id if city else None),
            )
        )
    if place is None:
        place = Place(external_place_id=geo.external_place_id, name=geo.name or ep.name)
        db.add(place)
    place.name = geo.name or ep.name
    place.category = ep.category
    place.cuisine = ep.cuisine
    # A hand-placed pin outranks the geocoder: re-analysis must never move it
    # back to a guess (or back to nothing). Enrichment below still refreshes.
    if place.location_source != "user":
        place.lat = geo.lat
        place.lng = geo.lng
        place.address = geo.address
        place.region = region
    place.rating = geo.rating
    place.review_count = geo.review_count
    place.price_level = geo.price_level
    place.photos = geo.photos or None
    place.hours = geo.hours
    place.utc_offset_minutes = geo.utc_offset_minutes
    place.phone = geo.phone
    place.business_status = geo.business_status
    place.google_maps_url = geo.google_maps_url
    place.last_verified_at = datetime.now(timezone.utc)
    place.city = city
    db.flush()
    return place


def _record_source(up: UserPlace, reel_id: str) -> None:
    """Track every reel a pin came from. Reassigns the list so SQLAlchemy sees
    the JSON column as dirty (in-place mutation isn't tracked)."""
    existing = up.sources or []
    if reel_id not in existing:
        up.sources = [*existing, reel_id]


def _upsert_user_place(
    db, user_id: str, place: Place, reel: ReelSource, ep, map_id: str
) -> tuple[UserPlace, bool]:
    """Returns (row, created).

    A place already pinned *on this map* is never added twice — whichever
    member added it, and from however many reels. The new reel is recorded as
    an extra source instead, so one venue is always exactly one pin per map.
    """
    existing = db.scalars(
        select(UserPlace).where(
            UserPlace.map_id == map_id,
            UserPlace.place_id == place.id,
        )
    ).first()
    if existing:
        _record_source(existing, reel.id)
        db.flush()
        return existing, False
    up = UserPlace(
        map_id=map_id,
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
        sources=[reel.id],
        confidence=ep.confidence,
    )
    db.add(up)
    db.flush()
    return up, True


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


def _get_or_create_city(
    db, name: str | None, country: str | None, region: str | None = None
) -> City | None:
    canonical = geocode.normalize_city(name, region)
    if not canonical:
        return None
    city = db.scalar(select(City).where(City.name == canonical, City.country == country))
    if city is None:
        city = City(name=canonical, country=country)
        db.add(city)
        db.flush()
    return city


def _link_existing_to_user(db, reel: ReelSource, user_id: str, map_id: str) -> int:
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
        # Already on this map from *any* reel — record the source, don't clone.
        already = db.scalars(
            select(UserPlace).where(
                UserPlace.map_id == map_id,
                UserPlace.place_id == t.place_id,
            )
        ).first()
        if already:
            _record_source(already, reel.id)
            continue
        db.add(UserPlace(
            map_id=map_id, user_id=user_id, place_id=t.place_id, reel_source_id=reel.id,
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


def _notify_other_members(db, map_id: str, actor_id: str, count: int) -> None:
    """Tell the *rest* of a shared map that someone added to it.

    This is what makes a shared map feel live without any websocket: the other
    members' phones buzz, and the app refreshes when they open it.
    """
    if count <= 0:
        return
    from app.models import Map, MapMember

    m = db.get(Map, map_id)
    if m is None or m.is_personal:
        return
    actor = db.get(User, actor_id)
    who = (actor.display_name if actor and actor.display_name else "Someone")
    others = [
        row.user_id
        for row in db.scalars(select(MapMember).where(MapMember.map_id == map_id))
        if row.user_id != actor_id
    ]
    for member_id in others:
        push.notify_user(
            member_id,
            title=m.name,
            body=f"{who} added {count} place{'s' if count != 1 else ''} 📍",
            deep_link=f"reelmap://maps/{map_id}",
        )


def _notify(user_id: str, count: int, reel: ReelSource) -> None:
    """Tell the phone how the reel turned out.

    Every outcome notifies, including the empty and failed ones: the user
    shared something and walked away, so silence just leaves them waiting for a
    buzz that never comes.
    """
    if count > 0:
        title = "Pins ready"
        body = f"{count} place{'s' if count != 1 else ''} saved from your reel 📍"
    elif reel.status == "unsupported":
        # The reason is already user-facing copy — repeating a generic "couldn't
        # analyze" here would just send them retrying something that can't work.
        title = "Nothing to pin"
        body = reel.error or "That reel doesn't have a place we can save."
    elif reel.status == "failed":
        title = "Couldn't analyze that reel"
        body = "Open Nosh to try it again."
    else:
        title = "No places in that reel"
        body = "We couldn't find any venues to save from it."
    push.notify_user(user_id, title=title, body=body,
                     deep_link=f"reelmap://reels/{reel.id}")
