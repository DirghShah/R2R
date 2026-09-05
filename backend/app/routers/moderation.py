"""Reporting and blocking.

App Store Guideline 1.2 requires both for any app with user-generated content.
The user content here is small but real: map names, display names, and the
places someone adds to a shared map.

Deliberately narrow. There is no messaging, no comments and no public profiles,
so "block" means "stop showing me this person's contributions" rather than
severing a social connection that does not exist.
"""
from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, HTTPException, Response
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.auth import get_current_user
from app.db import get_db
from app.models import Block, Map, Place, Report, User, UserPlace
from app.schemas import BlockOut, CreateBlockRequest, CreateReportRequest, ReportOut

log = logging.getLogger(__name__)

router = APIRouter(tags=["moderation"])

_TARGETS = {"map", "user", "place"}
_REASONS = {"offensive", "harassment", "spam", "illegal", "other"}


def _target_exists(db: Session, target_type: str, target_id: str) -> bool:
    model = {"map": Map, "user": User, "place": Place}[target_type]
    return db.get(model, target_id) is not None


@router.post("/reports", response_model=ReportOut, status_code=201)
def create_report(
    body: CreateReportRequest,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> ReportOut:
    if body.target_type not in _TARGETS:
        raise HTTPException(status_code=400, detail="Unknown report target")
    if body.reason not in _REASONS:
        raise HTTPException(status_code=400, detail="Unknown reason")
    if not _target_exists(db, body.target_type, body.target_id):
        raise HTTPException(status_code=404, detail="That content no longer exists")

    report = Report(
        reporter_id=user.id,
        target_type=body.target_type,
        target_id=body.target_id,
        reason=body.reason,
        note=(body.note or "").strip()[:1000] or None,
    )
    db.add(report)
    db.commit()

    # Surfaced in the worker/API logs so a report is visible without opening the
    # database. Apple asks how reports reach a human within 24 hours.
    log.warning(
        "[report] %s %s reported by %s — reason=%s note=%r",
        body.target_type, body.target_id, user.id, body.reason, report.note,
    )
    return ReportOut(
        id=report.id,
        target_type=report.target_type,
        target_id=report.target_id,
        reason=report.reason,
        status=report.status,
        created_at=report.created_at,
    )


@router.get("/blocks", response_model=list[BlockOut])
def list_blocks(
    user: User = Depends(get_current_user), db: Session = Depends(get_db)
) -> list[BlockOut]:
    rows = db.execute(
        select(Block, User)
        .join(User, User.id == Block.blocked_user_id)
        .where(Block.user_id == user.id)
        .order_by(Block.created_at.desc())
    ).all()
    return [
        BlockOut(user_id=u.id, display_name=u.display_name,
                 avatar_color=u.avatar_color, created_at=b.created_at)
        for b, u in rows
    ]


@router.post("/blocks", response_model=BlockOut, status_code=201)
def create_block(
    body: CreateBlockRequest,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> BlockOut:
    if body.user_id == user.id:
        raise HTTPException(status_code=400, detail="You can't block yourself")
    target = db.get(User, body.user_id)
    if target is None:
        raise HTTPException(status_code=404, detail="No such user")

    existing = db.scalar(
        select(Block).where(Block.user_id == user.id, Block.blocked_user_id == body.user_id)
    )
    if existing is None:
        db.add(Block(user_id=user.id, blocked_user_id=body.user_id))
        db.commit()

    return BlockOut(user_id=target.id, display_name=target.display_name,
                    avatar_color=target.avatar_color)


@router.delete("/blocks/{blocked_user_id}", status_code=204)
def delete_block(
    blocked_user_id: str,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> Response:
    block = db.scalar(
        select(Block).where(Block.user_id == user.id, Block.blocked_user_id == blocked_user_id)
    )
    if block is not None:
        db.delete(block)
        db.commit()
    return Response(status_code=204)


# --- shared helper --------------------------------------------------------


def blocked_ids(db: Session, user_id: str) -> set[str]:
    """Users this person has blocked. Used to filter what they're shown."""
    return set(
        db.scalars(select(Block.blocked_user_id).where(Block.user_id == user_id)).all()
    )
