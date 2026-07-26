"""Maps: create, share by link, join, manage members.

Sharing is by invite link to a specific map — there is no friend graph, no user
search, and no friend requests. Membership in a map *is* the relationship,
which means the feature works with a single existing user on day one and the
link doubles as the install funnel.
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Response
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.auth import get_current_user
from app.config import settings
from app.db import get_db
from app.maps import (
    generate_invite_code,
    member_count,
    personal_map,
    require_member,
    require_owner,
)
from app.models import Map, MapMember, User, UserPlace
from app.schemas import (
    CreateMapRequest,
    MapInviteOut,
    MapMemberOut,
    MapOut,
    MapPreviewOut,
    UpdateMapRequest,
)

router = APIRouter(tags=["maps"])


def _to_out(db: Session, m: Map, user_id: str) -> MapOut:
    places = len(list(db.scalars(select(UserPlace.id).where(UserPlace.map_id == m.id))))
    return MapOut(
        id=m.id,
        name=m.name,
        emoji=m.emoji,
        is_personal=m.is_personal,
        is_owner=m.owner_id == user_id,
        member_count=member_count(db, m.id),
        place_count=places,
        invite_code=m.invite_code if m.owner_id == user_id else None,
        created_at=m.created_at,
    )


@router.get("/maps", response_model=list[MapOut])
def list_maps(
    user: User = Depends(get_current_user), db: Session = Depends(get_db)
) -> list[MapOut]:
    personal_map(db, user.id)  # every user always has one
    db.commit()
    maps = db.scalars(
        select(Map).join(MapMember, MapMember.map_id == Map.id)
        .where(MapMember.user_id == user.id)
        .order_by(Map.is_personal.desc(), Map.created_at.asc())
    ).all()
    return [_to_out(db, m, user.id) for m in maps]


@router.post("/maps", response_model=MapOut, status_code=201)
def create_map(
    body: CreateMapRequest,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> MapOut:
    m = Map(name=body.name.strip(), emoji=body.emoji, owner_id=user.id)
    db.add(m)
    db.flush()
    db.add(MapMember(map_id=m.id, user_id=user.id, role="owner"))
    db.commit()
    return _to_out(db, m, user.id)


@router.patch("/maps/{map_id}", response_model=MapOut)
def update_map(
    map_id: str,
    body: UpdateMapRequest,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> MapOut:
    m = require_owner(db, map_id, user.id)
    if body.name is not None:
        m.name = body.name.strip()
    if body.emoji is not None:
        m.emoji = body.emoji
    db.commit()
    return _to_out(db, m, user.id)


@router.delete("/maps/{map_id}", status_code=204)
def delete_or_leave_map(
    map_id: str,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> Response:
    """Owner deletes the map for everyone; a member just leaves it.

    Same verb on purpose — from the member's point of view both mean "this is
    gone from my app" — but the UI must be explicit about which one is about to
    happen, because one of them is destructive for other people.
    """
    m = require_member(db, map_id, user.id)

    if m.owner_id != user.id:
        membership = db.scalar(
            select(MapMember).where(MapMember.map_id == map_id, MapMember.user_id == user.id)
        )
        db.delete(membership)
        db.commit()
        return Response(status_code=204)

    if m.is_personal:
        raise HTTPException(
            status_code=400,
            detail="Your personal map can't be deleted — shared reels need somewhere to land.",
        )

    for up in db.scalars(select(UserPlace).where(UserPlace.map_id == map_id)):
        db.delete(up)
    for member in db.scalars(select(MapMember).where(MapMember.map_id == map_id)):
        db.delete(member)
    db.delete(m)
    db.commit()
    return Response(status_code=204)


# --- sharing --------------------------------------------------------------


@router.post("/maps/{map_id}/invite", response_model=MapInviteOut)
def create_invite(
    map_id: str,
    rotate: bool = False,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> MapInviteOut:
    """Mint (or rotate) the invite code. Rotating kills every existing link."""
    m = require_owner(db, map_id, user.id)
    if m.invite_code is None or rotate:
        m.invite_code = generate_invite_code(db)
        db.commit()
    return MapInviteOut(
        map_id=m.id,
        invite_code=m.invite_code,
        invite_url=f"{settings.public_base_url.rstrip('/')}/join/{m.invite_code}",
    )


@router.get("/maps/preview/{code}", response_model=MapPreviewOut)
def preview_invite(code: str, db: Session = Depends(get_db)) -> MapPreviewOut:
    """Unauthenticated on purpose: the join screen shows what you're joining
    *before* asking anyone to sign in."""
    m = db.scalar(select(Map).where(Map.invite_code == code))
    if m is None:
        raise HTTPException(status_code=404, detail="That invite link is no longer valid.")
    owner = db.get(User, m.owner_id)
    return MapPreviewOut(
        name=m.name,
        emoji=m.emoji,
        owner_name=owner.display_name if owner else None,
        member_count=member_count(db, m.id),
    )


@router.post("/maps/join/{code}", response_model=MapOut)
def join_map(
    code: str,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> MapOut:
    m = db.scalar(select(Map).where(Map.invite_code == code))
    if m is None:
        raise HTTPException(status_code=404, detail="That invite link is no longer valid.")

    existing = db.scalar(
        select(MapMember).where(MapMember.map_id == m.id, MapMember.user_id == user.id)
    )
    if existing is None:  # joining twice is a no-op, not an error
        db.add(MapMember(map_id=m.id, user_id=user.id, role="editor"))
        db.commit()
    return _to_out(db, m, user.id)


@router.get("/maps/{map_id}/members", response_model=list[MapMemberOut])
def list_members(
    map_id: str,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> list[MapMemberOut]:
    require_member(db, map_id, user.id)
    rows = db.execute(
        select(MapMember, User)
        .join(User, User.id == MapMember.user_id)
        .where(MapMember.map_id == map_id)
        .order_by(MapMember.joined_at.asc())
    ).all()
    return [
        MapMemberOut(
            user_id=u.id,
            display_name=u.display_name,
            avatar_color=u.avatar_color,
            role=mem.role,
            joined_at=mem.joined_at,
        )
        for mem, u in rows
    ]


@router.delete("/maps/{map_id}/members/{member_user_id}", status_code=204)
def remove_member(
    map_id: str,
    member_user_id: str,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> Response:
    """The owner removes someone; anyone can remove themselves (leave)."""
    require_member(db, map_id, user.id)
    m = db.get(Map, map_id)
    if m.owner_id != user.id and member_user_id != user.id:
        raise HTTPException(status_code=403, detail="Only the owner can remove other members")
    if member_user_id == m.owner_id:
        raise HTTPException(status_code=400, detail="The owner can't be removed — delete the map instead")

    membership = db.scalar(
        select(MapMember).where(
            MapMember.map_id == map_id, MapMember.user_id == member_user_id
        )
    )
    if membership is not None:
        db.delete(membership)
        db.commit()
    return Response(status_code=204)
