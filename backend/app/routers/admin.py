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
from sqlalchemy.orm import Session

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
