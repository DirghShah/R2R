"""FastAPI application entrypoint."""
from __future__ import annotations

from fastapi import FastAPI

from app.config import settings
from app.db import Base, engine
from app.routers import auth as auth_router
from app.routers import places as places_router
from app.routers import reels as reels_router

app = FastAPI(title="ReelMap API", version="0.1.0")

app.include_router(auth_router.router)
app.include_router(reels_router.router)
app.include_router(places_router.router)


@app.on_event("startup")
def _startup() -> None:
    # For dev convenience, create tables on boot. In production use Alembic
    # migrations instead (see alembic/).
    if settings.environment == "dev":
        Base.metadata.create_all(bind=engine)


@app.get("/health")
def health() -> dict:
    return {"status": "ok", "env": settings.environment}
