"""Submit a reel for analysis + check status."""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.auth import get_current_user
from app.config import settings
from app.db import get_db
from app.models import ReelSource, User, UserPlace
from app.schemas import ReelStatusResponse, SubmitReelRequest
from worker.fetchers.base import canonical_id
from worker.queue import enqueue_analyze

router = APIRouter(tags=["reels"])


@router.post("/reels", response_model=ReelStatusResponse)
def submit_reel(
    body: SubmitReelRequest,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> ReelStatusResponse:
    try:
        cid = canonical_id(body.url)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    # Free-tier usage cap (monetization hook; generous while free).
    if user.plan == "free" and user.reels_this_month >= settings.free_monthly_reel_limit:
        raise HTTPException(status_code=402, detail="Monthly limit reached")

    reel = db.scalar(select(ReelSource).where(ReelSource.canonical_id == cid))
    if reel is None:
        reel = ReelSource(url=body.url, canonical_id=cid, status="pending")
        db.add(reel)
        db.commit()
        db.refresh(reel)

    user.reels_this_month += 1
    db.commit()

    enqueue_analyze(reel.id, user.id)
    return ReelStatusResponse(reel_id=reel.id, status=reel.status)


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
