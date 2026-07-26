"""Map membership helpers shared by the routers and the worker.

Access control is membership: if you're a member of a map you can read it and
add to it. There is no friend graph and no viewer role — being in the map *is*
the relationship.
"""
from __future__ import annotations

import secrets
import string

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Map, MapMember

# Unambiguous alphabet: no O/0, I/1/l — invite codes get read aloud and typed.
_CODE_ALPHABET = "ABCDEFGHJKMNPQRSTUVWXYZ23456789"
_CODE_LENGTH = 8


def generate_invite_code(db: Session) -> str:
    """A short, unguessable, unambiguous code. ~31^8 ≈ 8.5e11 possibilities."""
    for _ in range(10):
        code = "".join(secrets.choice(_CODE_ALPHABET) for _ in range(_CODE_LENGTH))
        if db.scalar(select(Map).where(Map.invite_code == code)) is None:
            return code
    raise HTTPException(status_code=500, detail="Could not allocate an invite code")


def personal_map(db: Session, user_id: str) -> Map:
    """The user's own map, created on demand.

    Created lazily rather than only at sign-up so that users who predate maps —
    and any path that missed the migration — still have somewhere for a share
    to land.
    """
    existing = db.scalar(
        select(Map).where(Map.owner_id == user_id, Map.is_personal.is_(True))
    )
    if existing is not None:
        return existing

    m = Map(name="My Map", emoji="📍", owner_id=user_id, is_personal=True)
    db.add(m)
    db.flush()
    db.add(MapMember(map_id=m.id, user_id=user_id, role="owner"))
    db.flush()
    return m


def member_map_ids(db: Session, user_id: str) -> list[str]:
    """Every map the user can see."""
    return list(db.scalars(select(MapMember.map_id).where(MapMember.user_id == user_id)))


def require_member(db: Session, map_id: str, user_id: str) -> Map:
    """404 rather than 403 for non-members — a stranger shouldn't be able to
    probe which map ids exist."""
    membership = db.scalar(
        select(MapMember).where(MapMember.map_id == map_id, MapMember.user_id == user_id)
    )
    if membership is None:
        raise HTTPException(status_code=404, detail="Map not found")
    m = db.get(Map, map_id)
    if m is None:
        raise HTTPException(status_code=404, detail="Map not found")
    return m


def require_owner(db: Session, map_id: str, user_id: str) -> Map:
    m = require_member(db, map_id, user_id)
    if m.owner_id != user_id:
        raise HTTPException(status_code=403, detail="Only the owner can do that")
    return m


def member_count(db: Session, map_id: str) -> int:
    return len(list(db.scalars(select(MapMember.id).where(MapMember.map_id == map_id))))
