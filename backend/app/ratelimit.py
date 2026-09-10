"""Fixed-window rate limiting backed by Redis.

`POST /reels` is a direct line to the Anthropic and Google Places bill — a reel
with 5 places costs ~$0.27 — so a public URL needs a ceiling on it. Auth is
limited too, since it is unauthenticated by definition.

Redis rather than an in-process counter on purpose: the API runs as more than
one replica in production, and a per-process limiter would multiply the real
limit by the replica count. Redis is already a hard dependency (RQ).

Fails **open**: if Redis is unreachable the request is allowed. A rate limiter
that takes the API down with it is worse than no rate limiter.
"""
from __future__ import annotations

import logging
import time

from fastapi import HTTPException, Request

from app.config import settings

log = logging.getLogger(__name__)


def _redis():
    # Imported lazily so tests and the CLI don't need a live Redis.
    from worker.queue import redis_conn

    return redis_conn


def _hit(bucket: str, limit: int, window_seconds: int = 3600) -> None:
    """Count one request against `bucket`; raise 429 once over `limit`."""
    if limit <= 0:
        return
    window = int(time.time()) // window_seconds
    key = f"rl:{bucket}:{window}"
    try:
        conn = _redis()
        used = conn.incr(key)
        if used == 1:
            # Only the first writer sets the TTL, so the window can't be
            # extended indefinitely by later hits.
            conn.expire(key, window_seconds)
    except Exception:  # noqa: BLE001 — never let the limiter break the API
        log.warning("ratelimit: redis unavailable, allowing request", exc_info=True)
        return

    if used > limit:
        raise HTTPException(
            status_code=429,
            detail="Too many requests. Try again a bit later.",
            headers={"Retry-After": str(window_seconds)},
        )


def _client_ip(request: Request) -> str:
    """Real client IP behind a PaaS load balancer."""
    forwarded = request.headers.get("x-forwarded-for")
    if forwarded:
        return forwarded.split(",")[0].strip()
    return request.client.host if request.client else "unknown"


def limit_reel_submission(user_id: str) -> None:
    """Per-user ceiling on analysis requests, on top of the monthly quota."""
    _hit(f"reels:{user_id}", settings.rate_limit_reels_per_hour)


def limit_auth(request: Request) -> None:
    """Per-IP ceiling on sign-in, which is unauthenticated by definition."""
    _hit(f"auth:{_client_ip(request)}", settings.rate_limit_auth_per_hour)


def limit_vibe_search(user_id: str) -> None:
    """Each search is a model call, so a stuck client retrying in a loop is a
    bill rather than just noise. Per minute, not per hour: searching is
    interactive, and an hourly bucket would lock someone out mid-session."""
    _hit(f"vibe:{user_id}", settings.vibe_search_per_minute, window_seconds=60)
