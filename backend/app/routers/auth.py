"""Auth, session refresh, profile, and account deletion."""
from __future__ import annotations

import hashlib

from fastapi import APIRouter, Depends, Request, Response
from sqlalchemy import select
from sqlalchemy.orm import Session

from app import apple
from app.auth import (
    create_access_token,
    get_current_user,
    issue_refresh_token,
    revoke_all_refresh_tokens,
    rotate_refresh_token,
    verify_apple_identity_token,
)
from app.db import get_db
from app.models import (
    Collection,
    Device,
    Map,
    MapMember,
    RefreshToken,
    User,
    UserPlace,
    UserReel,
)
from app.ratelimit import limit_auth
from app.schemas import (
    AppleAuthRequest,
    AuthResponse,
    RefreshRequest,
    RegisterDeviceRequest,
    UpdateMeRequest,
    UserOut,
)

router = APIRouter(tags=["auth"])

# Avatar colours, picked deterministically from the user id so the same person
# is the same colour on every device without storing an image anywhere.
_AVATAR_COLORS = [
    "#159A6A", "#2F6FE0", "#E0762F", "#B3439C",
    "#3AA6A6", "#C0563F", "#7A5AF8", "#D4A017",
]


def _avatar_color(user_id: str) -> str:
    digest = hashlib.sha256(user_id.encode()).digest()
    return _AVATAR_COLORS[digest[0] % len(_AVATAR_COLORS)]


@router.post("/auth/apple", response_model=AuthResponse)
def sign_in_with_apple(
    body: AppleAuthRequest, request: Request, db: Session = Depends(get_db)
) -> AuthResponse:
    limit_auth(request)
    apple_sub = verify_apple_identity_token(body.identity_token)

    user = db.scalar(select(User).where(User.apple_sub == apple_sub))
    if user is None:
        user = User(apple_sub=apple_sub, display_name=body.display_name)
        db.add(user)
        db.flush()
        user.avatar_color = _avatar_color(user.id)
    elif body.display_name and not user.display_name:
        # Apple only sends the name on the first authorization ever, so a user
        # who signed in before we captured names backfills on a later sign-in.
        user.display_name = body.display_name
    if user.avatar_color is None:
        user.avatar_color = _avatar_color(user.id)

    # Needed later to revoke Apple's grant on account deletion; failure here
    # must not block signing in.
    if body.authorization_code:
        token = apple.exchange_authorization_code(body.authorization_code)
        if token:
            user.apple_refresh_token = token

    db.commit()
    return AuthResponse(
        access_token=create_access_token(user.id),
        refresh_token=issue_refresh_token(db, user.id),
    )


@router.post("/auth/refresh", response_model=AuthResponse)
def refresh_session(
    body: RefreshRequest, request: Request, db: Session = Depends(get_db)
) -> AuthResponse:
    """Non-interactive re-auth.

    The Share Extension cannot present sign-in UI, so without this a share made
    after the access token expired could only ever be queued.
    """
    limit_auth(request)
    access, refresh = rotate_refresh_token(db, body.refresh_token)
    return AuthResponse(access_token=access, refresh_token=refresh)


@router.get("/me", response_model=UserOut)
def me(user: User = Depends(get_current_user)) -> User:
    return user


@router.patch("/me", response_model=UserOut)
def update_me(
    body: UpdateMeRequest,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> User:
    user.display_name = body.display_name.strip()
    db.commit()
    db.refresh(user)
    return user


@router.delete("/me", status_code=204)
def delete_account(
    user: User = Depends(get_current_user), db: Session = Depends(get_db)
) -> Response:
    """Delete the account and everything belonging to it.

    Also revokes Apple's grant — App Store Guideline 5.1.1(v) requires it, and
    deleting only our own rows does not satisfy review.

    Shared canonical rows (Place, ReelSource, City) are deliberately kept: they
    belong to no one user and other people's saves point at them.
    """
    if user.apple_refresh_token:
        apple.revoke(user.apple_refresh_token)

    user_id = user.id
    owned_map_ids = list(db.scalars(select(Map.id).where(Map.owner_id == user_id)))

    # Each phase is flushed before the next. SQLAlchemy orders deletes using ORM
    # *relationships*, and most of these tables reference users by a plain
    # foreign key with no relationship declared — so left to its own devices it
    # emits DELETE FROM users first and Postgres rejects the whole transaction.
    # Explicit flushes make the order ours rather than inferred.

    # 1. Pins. Those on maps this user owns go with the map. Those they added to
    #    *other people's* maps stay — they belong to that shared map now, not to
    #    whoever happened to add them — so reassign attribution to the map owner
    #    rather than leaving a dangling reference.
    for up in db.scalars(
        select(UserPlace).where(
            (UserPlace.user_id == user_id) | (UserPlace.map_id.in_(owned_map_ids))
        )
    ):
        if up.map_id in owned_map_ids:
            db.delete(up)
            continue
        owner_id = db.scalar(select(Map.owner_id).where(Map.id == up.map_id))
        if owner_id and owner_id != user_id:
            up.user_id = owner_id
        else:
            db.delete(up)
    db.flush()

    # 2. Memberships: this user's everywhere, plus everyone else's on their maps.
    for member in db.scalars(
        select(MapMember).where(
            (MapMember.user_id == user_id) | (MapMember.map_id.in_(owned_map_ids))
        )
    ):
        db.delete(member)
    db.flush()

    # 3. The maps themselves, now that nothing points at them.
    for m in db.scalars(select(Map).where(Map.id.in_(owned_map_ids))):
        db.delete(m)
    db.flush()

    # 4. Everything else hanging off the user.
    for model in (UserReel, Collection, Device, RefreshToken):
        for row in db.scalars(select(model).where(model.user_id == user_id)):
            db.delete(row)
    db.flush()

    # 5. Finally the user. Shared canonical rows (Place, ReelSource, City) are
    #    deliberately kept — they belong to no one user.
    db.delete(user)
    db.commit()
    return Response(status_code=204)


@router.post("/auth/signout", status_code=204)
def sign_out(
    user: User = Depends(get_current_user), db: Session = Depends(get_db)
) -> Response:
    revoke_all_refresh_tokens(db, user.id)
    return Response(status_code=204)


@router.post("/devices", status_code=204)
def register_device(
    body: RegisterDeviceRequest,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> None:
    existing = db.scalar(select(Device).where(Device.apns_token == body.apns_token))
    if existing:
        existing.user_id = user.id
    else:
        db.add(Device(user_id=user.id, apns_token=body.apns_token, platform=body.platform))
    db.commit()
