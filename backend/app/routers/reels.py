"""Submit a reel for analysis, list the user's activity feed, check status."""
from __future__ import annotations

from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.auth import get_current_user
from app.config import settings
from app.db import get_db
from app.models import ReelSource, User, UserPlace, UserReel
from app.ratelimit import limit_reel_submission
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
    limit_reel_submission(user.id)
    try:
        platform, cid = parse_source(body.url)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    reel = db.scalar(select(ReelSource).where(ReelSource.canonical_id == cid))

    # --- Known reel: reuse the stored analysis, never pay for it twice --------
    if reel is not None:
        _record_submission(db, user.id, reel.id)
        saved = _place_count(db, user.id, reel.id)

        # Still in flight — don't enqueue a second job for the same reel.
        if reel.status in ("pending", "processing"):
            db.commit()
            return ReelStatusResponse(reel_id=reel.id, status=reel.status,
                                      place_count=saved, already_analyzed=True)

        if reel.status == "done":
            db.commit()
            # The user already holds this reel's pins: nothing to do at all.
            # Otherwise queue the *link* job, which copies the cached places
            # across without re-running the fetch/vision/geocode pipeline.
            if saved == 0:
                enqueue_analyze(reel.id, user.id)
            return ReelStatusResponse(reel_id=reel.id, status="done",
                                      place_count=saved, already_analyzed=True)

        # Previously failed — retry it, but don't bill a failure to the quota.
        reel.status = "pending"
        reel.error = None
        db.commit()
        enqueue_analyze(reel.id, user.id)
        return ReelStatusResponse(reel_id=reel.id, status="pending")

    # --- New reel: this is the only path that costs an analysis --------------
    _roll_quota_period(user)
    if user.plan == "free" and user.reels_this_month >= settings.free_monthly_reel_limit:
        raise HTTPException(status_code=402, detail="Monthly limit reached")

    reel = ReelSource(url=body.url, canonical_id=cid, platform=platform, status="pending")
    db.add(reel)
    db.flush()
    _record_submission(db, user.id, reel.id)
    user.reels_this_month += 1
    db.commit()

    enqueue_analyze(reel.id, user.id)
    return ReelStatusResponse(reel_id=reel.id, status=reel.status)


def _roll_quota_period(user: User) -> None:
    """Start a fresh count when the calendar month turns over.

    Compares year/month rather than a duration so the reset lands on the 1st,
    and so a naive timestamp from SQLite compares fine against an aware one.
    """
    now = datetime.now(timezone.utc)
    start = user.quota_period_start
    if start is None or (start.year, start.month) != (now.year, now.month):
        user.reels_this_month = 0
        user.quota_period_start = now


def _record_submission(db: Session, user_id: str, reel_id: str) -> None:
    """Put the reel in this user's activity feed (idempotent)."""
    link = db.scalar(
        select(UserReel).where(UserReel.user_id == user_id, UserReel.reel_source_id == reel_id)
    )
    if link is None:
        db.add(UserReel(user_id=user_id, reel_source_id=reel_id))


def _place_count(db: Session, user_id: str, reel_id: str) -> int:
    """How many of the user's saved places came from this reel — counting the
    ones deduped onto an earlier pin, which record the reel in `sources`."""
    rows = db.execute(
        select(UserPlace.reel_source_id, UserPlace.sources).where(UserPlace.user_id == user_id)
    ).all()
    return sum(
        1 for source_id, sources in rows
        if source_id == reel_id or reel_id in (sources or [])
    )


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

    # One pass over the user's places, then count per reel in memory — a COUNT
    # per row would be an N+1 against the whole feed.
    saved = db.execute(
        select(UserPlace.reel_source_id, UserPlace.sources).where(UserPlace.user_id == user.id)
    ).all()
    counts: dict[str, int] = {}
    for source_id, sources in saved:
        for reel_id in {source_id, *(sources or [])}:
            counts[reel_id] = counts.get(reel_id, 0) + 1

    return [
        ReelActivityOut(
            reel_id=reel.id,
            status=reel.status,
            platform=reel.platform,
            title=_title(reel),
            thumbnail_url=reel.thumbnail_url,
            place_count=counts.get(reel.id, 0),
            error=reel.error,
            created_at=created,
        )
        for reel, created in rows
    ]


@router.get("/reels/{reel_id}", response_model=ReelStatusResponse)
def reel_status(
    reel_id: str,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> ReelStatusResponse:
    # Ownership check, not just existence: without the UserReel join any
    # authenticated user could read any reel's status and error by id.
    reel = db.scalar(
        select(ReelSource)
        .join(UserReel, UserReel.reel_source_id == ReelSource.id)
        .where(ReelSource.id == reel_id, UserReel.user_id == user.id)
    )
    if reel is None:
        raise HTTPException(status_code=404, detail="Reel not found")
    return ReelStatusResponse(
        reel_id=reel.id,
        status=reel.status,
        place_count=_place_count(db, user.id, reel.id),
        error=reel.error,
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
