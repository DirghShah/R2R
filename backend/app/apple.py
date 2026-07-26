"""Apple ID token exchange and revocation.

App Store Guideline 5.1.1(v) requires that deleting an account also revokes the
app's Sign in with Apple grant — deleting our own rows is not sufficient. To do
that we need Apple's *refresh* token, which is only obtainable by exchanging the
one-time `authorizationCode` the client receives at sign-in.

Everything here degrades to a no-op when the Sign in with Apple key isn't
configured, so local dev and tests are unaffected.
"""
from __future__ import annotations

import base64
import logging
from datetime import datetime, timedelta, timezone

import httpx
from jose import jwt

from app.config import settings

log = logging.getLogger(__name__)

_TOKEN_URL = "https://appleid.apple.com/auth/token"
_REVOKE_URL = "https://appleid.apple.com/auth/revoke"
_AUDIENCE = "https://appleid.apple.com"


def is_configured() -> bool:
    return bool(
        settings.apple_team_id and settings.apple_key_id and settings.apple_private_key
    )


def _client_secret() -> str:
    """Apple wants a short-lived JWT signed with the Sign in with Apple key in
    place of a static client secret."""
    private_key = base64.b64decode(settings.apple_private_key).decode()
    now = datetime.now(timezone.utc)
    return jwt.encode(
        {
            "iss": settings.apple_team_id,
            "iat": int(now.timestamp()),
            "exp": int((now + timedelta(minutes=settings.apple_client_secret_ttl_minutes)).timestamp()),
            "aud": _AUDIENCE,
            "sub": settings.apple_bundle_id,
        },
        private_key,
        algorithm="ES256",
        headers={"kid": settings.apple_key_id},
    )


def exchange_authorization_code(code: str) -> str | None:
    """Swap the one-time code from the client for a long-lived refresh token.

    Returns None on any failure: sign-in must still succeed even if we can't
    store the token, we just lose the ability to revoke later.
    """
    if not is_configured() or not code:
        return None
    try:
        resp = httpx.post(
            _TOKEN_URL,
            data={
                "client_id": settings.apple_bundle_id,
                "client_secret": _client_secret(),
                "code": code,
                "grant_type": "authorization_code",
            },
            timeout=15,
        )
        resp.raise_for_status()
        return resp.json().get("refresh_token")
    except Exception:  # noqa: BLE001
        log.warning("apple: authorization_code exchange failed", exc_info=True)
        return None


def revoke(refresh_token: str) -> bool:
    """Revoke the app's Apple grant. Returns True if Apple accepted it."""
    if not is_configured() or not refresh_token:
        return False
    try:
        resp = httpx.post(
            _REVOKE_URL,
            data={
                "client_id": settings.apple_bundle_id,
                "client_secret": _client_secret(),
                "token": refresh_token,
                "token_type_hint": "refresh_token",
            },
            timeout=15,
        )
        resp.raise_for_status()
        return True
    except Exception:  # noqa: BLE001 — deletion must proceed regardless
        log.warning("apple: token revocation failed", exc_info=True)
        return False
