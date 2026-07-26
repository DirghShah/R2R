"""FastAPI application entrypoint."""
from __future__ import annotations

import logging

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.config import settings
from app.routers import auth as auth_router
from app.routers import links as links_router
from app.routers import maps as maps_router
from app.routers import places as places_router
from app.routers import reels as reels_router

log = logging.getLogger(__name__)

app = FastAPI(title="ReelMap API", version="0.1.0")

# The API is consumed by a native iOS app, never a browser, so the allowlist is
# empty by default rather than open. Set CORS_ALLOW_ORIGINS only if something
# genuinely needs it (e.g. a future web client).
if settings.cors_allow_origins:
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_allow_origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

app.include_router(auth_router.router)
app.include_router(maps_router.router)
app.include_router(links_router.router)
app.include_router(reels_router.router)
app.include_router(places_router.router)


@app.on_event("startup")
def _startup() -> None:
    """Schema is owned by Alembic (`alembic upgrade head`), in every environment.

    This used to `create_all` plus replay a list of `ALTER TABLE ... IF NOT
    EXISTS` strings, which only ran in dev and left production with no tables at
    all. Migrations now run as a deploy step instead — see backend/README.md.
    """
    log.info("ReelMap API starting (env=%s)", settings.environment)


@app.get("/health")
def health() -> dict:
    return {"status": "ok", "env": settings.environment}
