"""Submit a reel for analysis, list the user's activity feed, check status."""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.auth import get_current_user
from app.config import settings
from app.db import get_db
from app.models import ReelSource, User, UserPlace, UserReel
from app.schemas import ReelActivityOut, ReelStatusResponse, SubmitReelRequest
from worker.fetchers.base import parse_source
from worker.queue import enqueue_analyze

router = APIRouter(tags=["reels"])


@router.post("/reels", response_model=ReelStatusResponse)
def submit_reel(
    body: SubmitReelRequest,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> ReelStatusResponse:
    try:
        platform, cid = parse_source(body.url)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    # Free-tier usage cap (monetization hook; generous while free).
    if user.plan == "free" and user.reels_this_month >= settings.free_monthly_reel_limit:
        raise HTTPException(status_code=402, detail="Monthly limit reached")

    reel = db.scalar(select(ReelSource).where(ReelSource.canonical_id == cid))
    if reel is None:
        reel = ReelSource(url=body.url, canonical_id=cid, platform=platform, status="pending")
        db.add(reel)
        db.commit()
        db.refresh(reel)

    # Record the submission so it shows in this user's activity/queue feed.
    link = db.scalar(
        select(UserReel).where(UserReel.user_id == user.id, UserReel.reel_source_id == reel.id)
    )
    if link is None:
        db.add(UserReel(user_id=user.id, reel_source_id=reel.id))

    user.reels_this_month += 1
    db.commit()

    enqueue_analyze(reel.id, user.id)
    return ReelStatusResponse(reel_id=reel.id, status=reel.status)


@router.get("/reels", response_model=list[ReelActivityOut])
def list_activity(
    limit: int = 30,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> list[ReelActivityOut]:
    """The user's reels, newest-first, with live status — powers the queue UI."""
    rows = db.execute(
        select(ReelSource, UserReel.created_at)
        .join(UserReel, UserReel.reel_source_id == ReelSource.id)
        .where(UserReel.user_id == user.id)
        .order_by(UserReel.created_at.desc())
        .limit(min(limit, 100))
    ).all()

    out: list[ReelActivityOut] = []
    for reel, created in rows:
        count = db.scalar(
            select(func.count())
            .select_from(UserPlace)
            .where(UserPlace.user_id == user.id, UserPlace.reel_source_id == reel.id)
        )
        out.append(
            ReelActivityOut(
                reel_id=reel.id,
                status=reel.status,
                platform=reel.platform,
                title=_title(reel),
                thumbnail_url=reel.thumbnail_url,
                place_count=count or 0,
                error=reel.error,
                created_at=created,
            )
        )
    return out


@router.get("/reels/{reel_id}", response_model=ReelStatusResponse)
def reel_status(
    reel_id: str,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> ReelStatusResponse:
    reel = db.get(ReelSource, reel_id)
    if reel is None:
        raise HTTPException(status_code=404, detail="Reel not found")
    count = db.scalar(
        select(func.count())
        .select_from(UserPlace)
        .where(UserPlace.user_id == user.id, UserPlace.reel_source_id == reel.id)
    )
    return ReelStatusResponse(
        reel_id=reel.id, status=reel.status, place_count=count or 0, error=reel.error
    )


def _title(reel: ReelSource) -> str | None:
    """A short human label for the queue row."""
    if reel.caption:
        first = reel.caption.strip().splitlines()[0].strip()
        if first:
            return first[:80]
    if reel.author_handle:
        return f"@{reel.author_handle}"
    return None
