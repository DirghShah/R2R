"""Sign in with Apple verification + app JWT issuance/validation."""
from __future__ import annotations

import hashlib
import logging
import secrets
import threading
import time
from datetime import datetime, timedelta, timezone

import httpx
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from jose import jwt
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import settings
from app.db import get_db
from app.models import RefreshToken, User

log = logging.getLogger(__name__)

_bearer = HTTPBearer(auto_error=True)
_APPLE_KEYS_URL = "https://appleid.apple.com/auth/keys"
_APPLE_ISSUER = "https://appleid.apple.com"

# Apple's signing keys rotate rarely. Fetching them on every sign-in put an
# Apple round-trip (and an Apple outage) in the critical path of every login.
_JWKS_TTL_SECONDS = 6 * 3600
_jwks_cache: tuple[float, list[dict]] | None = None
_jwks_lock = threading.Lock()


def _apple_keys(force_refresh: bool = False) -> list[dict]:
    """Apple's JWKS, cached. `force_refresh` handles key rotation: an unknown
    `kid` means our cache is stale, not that the token is forged."""
    global _jwks_cache
    with _jwks_lock:
        cached = _jwks_cache
        fresh = cached is not None and (time.time() - cached[0]) < _JWKS_TTL_SECONDS
        if cached is not None and fresh and not force_refresh:
            return cached[1]
        try:
            keys = httpx.get(_APPLE_KEYS_URL, timeout=15).json()["keys"]
        except Exception:  # noqa: BLE001
            if cached is not None:
                # Serve stale keys rather than fail every login during an
                # Apple/network blip.
                log.warning("apple JWKS fetch failed; using cached keys", exc_info=True)
                return cached[1]
            raise
        _jwks_cache = (time.time(), keys)
        return keys


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
        header = jwt.get_unverified_header(identity_token)
        keys = _apple_keys()
        key = next((k for k in keys if k["kid"] == header["kid"]), None)
        if key is None:  # cache predates a key rotation — refetch once
            key = next(k for k in _apple_keys(force_refresh=True) if k["kid"] == header["kid"])
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


# --- Refresh tokens -------------------------------------------------------
#
# The Share Extension runs in its own process and can never present sign-in UI,
# so when the access token expires mid-share it has no interactive way back.
# A rotating refresh token gives it a non-interactive path.


def _hash_token(raw: str) -> str:
    return hashlib.sha256(raw.encode()).hexdigest()


def issue_refresh_token(db: Session, user_id: str) -> str:
    """Mint a refresh token, returning the raw value (stored only as a hash)."""
    raw = secrets.token_urlsafe(48)
    db.add(RefreshToken(
        user_id=user_id,
        token_hash=_hash_token(raw),
        expires_at=datetime.now(timezone.utc) + timedelta(days=settings.refresh_token_days),
    ))
    db.commit()
    return raw


def rotate_refresh_token(db: Session, raw: str) -> tuple[str, str]:
    """Exchange a refresh token for (access_token, new_refresh_token).

    Rotates on every use: a token that is presented twice is either replayed or
    stolen, and either way the old one must stop working.
    """
    row = db.scalar(select(RefreshToken).where(RefreshToken.token_hash == _hash_token(raw)))
    now = datetime.now(timezone.utc)
    expires = row.expires_at if row else None
    if expires is not None and expires.tzinfo is None:  # SQLite returns naive
        expires = expires.replace(tzinfo=timezone.utc)

    if row is None or row.revoked_at is not None or (expires and expires < now):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED,
                            detail="Session expired. Please sign in again.")

    row.revoked_at = now
    db.commit()
    return create_access_token(row.user_id), issue_refresh_token(db, row.user_id)


def revoke_all_refresh_tokens(db: Session, user_id: str) -> None:
    now = datetime.now(timezone.utc)
    for row in db.scalars(select(RefreshToken).where(
        RefreshToken.user_id == user_id, RefreshToken.revoked_at.is_(None)
    )):
        row.revoked_at = now
    db.commit()
