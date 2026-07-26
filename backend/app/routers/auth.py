"""Auth + device registration."""
from __future__ import annotations

from fastapi import APIRouter, Depends, Request
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.auth import create_access_token, get_current_user, verify_apple_identity_token
from app.db import get_db
from app.models import Device, User
from app.ratelimit import limit_auth
from app.schemas import AppleAuthRequest, AuthResponse, RegisterDeviceRequest

router = APIRouter(tags=["auth"])


@router.post("/auth/apple", response_model=AuthResponse)
def sign_in_with_apple(
    body: AppleAuthRequest, request: Request, db: Session = Depends(get_db)
) -> AuthResponse:
    limit_auth(request)
    apple_sub = verify_apple_identity_token(body.identity_token)
    user = db.scalar(select(User).where(User.apple_sub == apple_sub))
    if user is None:
        user = User(apple_sub=apple_sub)
        db.add(user)
        db.commit()
        db.refresh(user)
    return AuthResponse(access_token=create_access_token(user.id))


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
