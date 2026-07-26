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
from app.models import Collection, Device, RefreshToken, User, UserPlace, UserReel
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
    for model in (UserPlace, UserReel, Collection, Device, RefreshToken):
        for row in db.scalars(select(model).where(model.user_id == user_id)):
            db.delete(row)
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
