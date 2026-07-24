"""FastAPI application entrypoint."""
from __future__ import annotations

from fastapi import FastAPI
from sqlalchemy import text

from app.config import settings
from app.db import Base, engine
from app.routers import auth as auth_router
from app.routers import places as places_router
from app.routers import reels as reels_router

app = FastAPI(title="ReelMap API", version="0.1.0")

app.include_router(auth_router.router)
app.include_router(reels_router.router)
app.include_router(places_router.router)

# Idempotent dev migrations for columns added after a table already exists
# (create_all only creates missing tables, it never ALTERs existing ones).
_DEV_MIGRATIONS = [
    "ALTER TABLE places ADD COLUMN IF NOT EXISTS cuisine VARCHAR",
]


@app.on_event("startup")
def _startup() -> None:
    # For dev convenience, create tables on boot. In production use Alembic
    # migrations instead (see alembic/).
    if settings.environment != "dev":
        return
    Base.metadata.create_all(bind=engine)
    for stmt in _DEV_MIGRATIONS:
        try:
            with engine.begin() as conn:  # own txn: a no-op/failure can't abort the rest
                conn.execute(text(stmt))
        except Exception:  # noqa: BLE001 - already applied / unsupported dialect
            pass


@app.get("/health")
def health() -> dict:
    return {"status": "ok", "env": settings.environment}
