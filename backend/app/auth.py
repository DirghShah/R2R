"""Sign in with Apple verification + app JWT issuance/validation."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import httpx
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from jose import jwt
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import settings
from app.db import get_db
from app.models import User

_bearer = HTTPBearer(auto_error=True)
_APPLE_KEYS_URL = "https://appleid.apple.com/auth/keys"
_APPLE_ISSUER = "https://appleid.apple.com"


def create_access_token(user_id: str) -> str:
    expire = datetime.now(timezone.utc) + timedelta(hours=settings.jwt_expiry_hours)
    payload = {"sub": user_id, "exp": expire}
    return jwt.encode(payload, settings.jwt_secret, algorithm=settings.jwt_algorithm)


def verify_apple_identity_token(identity_token: str) -> str:
    """Return the Apple subject (stable user id). Dev shortcut: a token of the
    form 'dev:<sub>' is accepted only when environment=dev."""
    if settings.environment == "dev" and identity_token.startswith("dev:"):
        return identity_token.split(":", 1)[1]

    try:
        keys = httpx.get(_APPLE_KEYS_URL, timeout=15).json()["keys"]
        header = jwt.get_unverified_header(identity_token)
        key = next(k for k in keys if k["kid"] == header["kid"])
        claims = jwt.decode(
            identity_token,
            key,
            algorithms=["RS256"],
            audience=settings.apple_bundle_id,
            issuer=_APPLE_ISSUER,
        )
        return claims["sub"]
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=f"Invalid Apple identity token: {exc}",
        ) from exc


def get_current_user(
    creds: HTTPAuthorizationCredentials = Depends(_bearer),
    db: Session = Depends(get_db),
) -> User:
    try:
        payload = jwt.decode(
            creds.credentials, settings.jwt_secret, algorithms=[settings.jwt_algorithm]
        )
        user_id = payload["sub"]
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid token"
        ) from exc

    user = db.scalar(select(User).where(User.id == user_id))
    if user is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Unknown user")
    return user
