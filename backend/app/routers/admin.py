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
        "cost_usd": {
            "last_24h": _cost(ReelSource.created_at >= day),
            "last_30d": cost_month,
            "all_time": _cost(),
            # The number that actually matters. Google Places dominates, so
            # this rises with places-per-reel, not with reel count.
            "avg_per_reel_30d": round(cost_month / reels_month, 4) if reels_month else 0.0,
        },
    }
