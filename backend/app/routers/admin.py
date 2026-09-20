"""Operational stats: what's been analysed, and what it cost.

Deliberately *not* a web dashboard with a login. A login is an authentication
surface on a public site, needs session handling and CSRF, and would exist for
an audience of one. This is a single token-guarded JSON endpoint — open it in a
browser or curl it — and it can be the data source if a UI is ever worth
building.

Returns aggregates only. No place names, no map names, no reel URLs: there is
no reason for an ops view to expose what individual people saved.
"""
from __future__ import annotations

import secrets
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, Header, HTTPException
from sqlalchemy import func, select
from sqlalchemy.orm import Session, joinedload

from app.config import settings
from app.db import get_db
from app.models import Map, Place, ReelSource, User, UserPlace

router = APIRouter(tags=["admin"], include_in_schema=False)


def _require_admin(authorization: str | None = Header(default=None)) -> None:
    """Bearer token, compared in constant time.

    404 rather than 401 when ADMIN_TOKEN is unset: an endpoint that answers
    "unauthorized" has told an attacker it exists.
    """
    if not settings.admin_token:
        raise HTTPException(status_code=404, detail="Not Found")
    supplied = (authorization or "").removeprefix("Bearer ").strip()
    if not secrets.compare_digest(supplied, settings.admin_token):
        raise HTTPException(status_code=404, detail="Not Found")


@router.get("/admin/stats", dependencies=[Depends(_require_admin)])
def stats(db: Session = Depends(get_db)) -> dict:
    now = datetime.now(timezone.utc)
    day = now - timedelta(days=1)
    month = now - timedelta(days=30)

    def _count(model, *where) -> int:
        return db.scalar(select(func.count()).select_from(model).where(*where)) or 0

    def _cost(*where) -> float:
        return round(db.scalar(
            select(func.coalesce(func.sum(ReelSource.cost_usd), 0.0)).where(*where)
        ) or 0.0, 2)

    by_status = dict(db.execute(
        select(ReelSource.status, func.count()).group_by(ReelSource.status)
    ).all())

    reels_month = _count(ReelSource, ReelSource.created_at >= month)
    cost_month = _cost(ReelSource.created_at >= month)
    avg_reel = cost_month / reels_month if reels_month else 0.0
    fixed = _fixed_costs()

    done = by_status.get("done", 0)
    places_per_reel = (_count(Place) / done) if done else 0.0
    total_reels = _count(ReelSource)
    unsupported_share = (
        by_status.get("unsupported", 0) / total_reels if total_reels else 0.0
    )

    return {
        "generated_at": now.isoformat(),
        "users": {
            "total": _count(User),
            "new_24h": _count(User, User.created_at >= day),
            "new_30d": _count(User, User.created_at >= month),
        },
        "reels": {
            "total": _count(ReelSource),
            "by_status": by_status,
            "last_24h": _count(ReelSource, ReelSource.created_at >= day),
            "last_30d": reels_month,
            # A reel stuck here longer than the stale window means the worker
            # died mid-job. Anything above zero is worth looking at.
            "stuck": _count(
                ReelSource,
                ReelSource.status == "processing",
                ReelSource.started_at
                < now - timedelta(minutes=settings.stale_reel_minutes),
            ),
        },
        "places": {
            "canonical": _count(Place),
            "saved": _count(UserPlace),
            "maps": _count(Map),
            "shared_maps": db.scalar(
                select(func.count()).select_from(
                    select(Map.id).join(Map.members).group_by(Map.id)
                    .having(func.count() > 1).subquery()
                )
            ) or 0,
        },
        # What is configured right now, which is the first thing to check when a
        # cost looks wrong — the model in particular, since the code default is
        # the most expensive one and it is easy to leave unset.
        "config": {
            "environment": settings.environment,
            "claude_model": settings.anthropic_model,
            "reel_fetcher": settings.reel_fetcher,
            "geocoder": settings.geocoder,
            "free_monthly_reel_limit": settings.free_monthly_reel_limit,
        },
        "cost_usd": {
            "last_24h": _cost(ReelSource.created_at >= day),
            "last_30d": cost_month,
            "all_time": _cost(),
            "avg_per_reel_30d": round(cost_month / reels_month, 4) if reels_month else 0.0,
            # Where the money went. Reading a total without this tells you
            # nothing about which lever to pull.
            "by_vendor_all_time": _by_vendor(db),
            "fixed": fixed,
            # Reels are currently a rounding error next to hosting, so a monthly
            # figure that ignores fixed cost is the wrong number to quote.
            "total_monthly_estimate": round(fixed["monthly_equivalent"] + cost_month, 2),
        },
        # Whether the place cache is actually earning its keep. Reads straight
        # off the stored breakdowns, so it can't drift from what was billed.
        "cache": _cache_effect(db),
        "unit_economics": {
            # What one more user who fills the free tier would cost.
            "cost_of_a_maxed_free_user_monthly": round(
                avg_reel * settings.free_monthly_reel_limit, 2
            ),
            "avg_places_per_reel": round(places_per_reel, 2),
            "share_of_reels_with_no_places": round(unsupported_share, 3),
        },
    }


def _by_vendor(db: Session) -> dict:
    """Vendor split, summed from each reel's stored breakdown.

    Reels analysed before cost_detail existed contribute their total under
    "unattributed" rather than being silently dropped or guessed at — a
    breakdown that doesn't add up to the total is worse than one with a gap in
    it that says so.
    """
    totals = {"claude": 0.0, "fetch": 0.0, "geocode": 0.0, "unattributed": 0.0}
    rows = db.execute(select(ReelSource.cost_usd, ReelSource.cost_detail)).all()
    for cost, detail in rows:
        if not detail:
            totals["unattributed"] += cost or 0.0
            continue
        totals["claude"] += detail.get("claude_usd", 0.0)
        totals["fetch"] += detail.get("fetch_usd", 0.0)
        totals["geocode"] += detail.get("geocode_usd", 0.0)
    return {k: round(v, 4) for k, v in totals.items()}


def _cache_effect(db: Session) -> dict:
    """How many places were reused instead of looked up, and what that saved.

    Only counts reels analysed since the breakdown started recording both
    numbers; earlier ones have nothing to compare.
    """
    saved_places = looked_up = 0
    for (detail,) in db.execute(select(ReelSource.cost_detail)).all():
        if not detail or "places_searched" not in detail:
            continue
        saved_places += detail.get("places", 0)
        looked_up += detail.get("places_searched", 0)
    reused = max(saved_places - looked_up, 0)
    return {
        "places_from_cache": reused,
        "places_looked_up": looked_up,
        "hit_rate": round(reused / saved_places, 3) if saved_places else 0.0,
        "saved_usd": round(reused * settings.google_cost_per_place, 4),
    }


def _fixed_costs() -> dict:
    """Subscriptions and one-off spend, with a monthly equivalent.

    Annual is divided by twelve. A one-off is counted once in `one_time_total`
    and left out of the monthly figure, because amortising a purchase over an
    arbitrary window invents a number.
    """
    items = settings.fixed_cost_items()
    monthly = sum(i["usd"] for i in items if i["period"] == "monthly")
    annual = sum(i["usd"] for i in items if i["period"] == "annual")
    once = sum(i["usd"] for i in items if i["period"] == "once")
    return {
        "items": items,
        "monthly_equivalent": round(monthly + annual / 12, 2),
        "annual_equivalent": round(monthly * 12 + annual, 2),
        "one_time_total": round(once, 2),
    }


@router.get("/admin/reels", dependencies=[Depends(_require_admin)])
def reel_ledger(
    limit: int = 100,
    offset: int = 0,
    status: str | None = None,
    db: Session = Depends(get_db),
) -> dict:
    """Every reel analysed, newest first, with what each one cost.

    The aggregate answers "what am I spending"; this answers "on what" — which
    reel was expensive, whether the expensive ones produced places, and whether
    a run predates a model change. Still no URLs or captions: an ops view has no
    business holding what individual people saved.
    """
    stmt = select(ReelSource).order_by(ReelSource.created_at.desc())
    if status:
        stmt = stmt.where(ReelSource.status == status)

    total = db.scalar(
        select(func.count()).select_from(ReelSource).where(
            *( [ReelSource.status == status] if status else [] )
        )
    ) or 0

    rows = db.scalars(stmt.limit(min(limit, 500)).offset(max(offset, 0))).all()

    def _row(r: ReelSource) -> dict:
        d = r.cost_detail or {}
        return {
            "id": r.id,
            "platform": r.platform,
            "status": r.status,
            "created_at": r.created_at.isoformat() if r.created_at else None,
            "analyzed_at": r.analyzed_at.isoformat() if r.analyzed_at else None,
            "seconds": (
                round((r.analyzed_at - r.created_at).total_seconds(), 1)
                if r.analyzed_at and r.created_at else None
            ),
            "places": d.get("places"),
            "model": d.get("model"),
            "input_tokens": d.get("input_tokens"),
            "output_tokens": d.get("output_tokens"),
            "claude_usd": d.get("claude_usd"),
            "fetch_usd": d.get("fetch_usd"),
            "geocode_usd": d.get("geocode_usd"),
            "cost_usd": r.cost_usd,
        }

    return {
        "total": total,
        "limit": limit,
        "offset": offset,
        "reels": [_row(r) for r in rows],
    }


@router.get("/admin/example-candidates", dependencies=[Depends(_require_admin)])
def example_candidates(limit: int = 5, db: Session = Depends(get_db)) -> dict:
    """Rank analysed reels by how good an onboarding example they'd make.

    EXAMPLE_REEL_URL decides what every new user sees in their first thirty
    seconds, and picking it by scrolling a list of ids is guesswork. This scores
    the things that actually matter for that moment.

    The one endpoint here that returns reel URLs and place names. That is the
    point of it: you are choosing what to make public, so you have to be able to
    see the candidates. It stays behind the same admin token as everything else.
    """
    rows = db.scalars(
        select(ReelSource).where(ReelSource.status == "done")
    ).all()

    scored = []
    for reel in rows:
        saves = db.scalars(
            select(UserPlace)
            .options(joinedload(UserPlace.place).joinedload(Place.city))
            .where(UserPlace.reel_source_id == reel.id)
        ).unique().all()
        # One canonical place may be saved by several people; the example adds
        # the distinct set, so that is what counts.
        by_place = {up.place_id: up for up in saves if up.place is not None}
        places = list(by_place.values())
        if not places:
            continue

        cities = {up.place.city.name for up in places if up.place.city}
        tips = sum(len(up.tips or []) + len(up.what_to_order or []) for up in places)
        pinned = sum(1 for up in places if up.place.lat is not None)
        with_photo = sum(1 for up in places if up.place.photos)

        scored.append({
            "score": round(_example_score(len(places), len(cities), tips,
                                          pinned, with_photo), 2),
            "url": reel.url,
            "platform": reel.platform,
            "author_handle": reel.author_handle,
            "places": len(places),
            "pinned": pinned,
            "with_photos": with_photo,
            "cities": sorted(cities),
            "tip_lines": tips,
            "place_names": [up.place.name for up in places][:6],
            "why": _example_verdict(len(places), len(cities), tips, pinned),
        })

    scored.sort(key=lambda c: -c["score"])
    return {"candidates": scored[:max(1, min(limit, 20))], "considered": len(rows)}


def _example_score(places: int, cities: int, tips: int,
                   pinned: int, with_photos: int) -> float:
    """What makes a first-run demo land, weighted by how much it matters.

    Tips carry the most weight because they are the part nobody expects.
    Anyone can drop pins on a map; a new user tapping one and reading "cash
    only after 9pm" is the moment the app stops looking like a bookmark folder.
    """
    if places == 0 or pinned == 0:
        return 0.0

    # Three to five is the sweet spot. One place is underwhelming, and a
    # nine-place roundup buries the moment under a wall of pins.
    if 3 <= places <= 5:
        size = 1.0
    elif places == 2 or places == 6:
        size = 0.6
    else:
        size = 0.2

    # The map animates to fit the pins, so two cities zooms out to a continent
    # and it looks like nothing happened.
    focus = 1.0 if cities == 1 else (0.3 if cities == 2 else 0.0)

    richness = min(tips / (places * 3.0), 1.0)   # ~3 lines a place is plenty
    complete = (pinned / places) * 0.5 + (with_photos / places) * 0.5

    return 40 * richness + 25 * size + 20 * focus + 15 * complete


def _example_verdict(places: int, cities: int, tips: int, pinned: int) -> str:
    """Why this one isn't the obvious pick, in plain words."""
    faults = []
    if places < 3:
        faults.append("too few places to impress")
    elif places > 5:
        faults.append(f"{places} places floods a new map")
    if cities > 1:
        faults.append(f"spans {cities} cities, so the map zooms out too far")
    if tips < places * 2:
        faults.append("thin on tips, which is the part that sells it")
    if pinned < places:
        faults.append(f"{places - pinned} place(s) never got a pin")
    return "; ".join(faults) or "good on every count"
