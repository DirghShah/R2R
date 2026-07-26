"""FastAPI application entrypoint."""
from __future__ import annotations

from fastapi import FastAPI
from sqlalchemy import select, text

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
    "ALTER TABLE places ADD COLUMN IF NOT EXISTS review_count INTEGER",
    "ALTER TABLE places ADD COLUMN IF NOT EXISTS phone VARCHAR",
    "ALTER TABLE places ADD COLUMN IF NOT EXISTS business_status VARCHAR",
    "ALTER TABLE places ADD COLUMN IF NOT EXISTS google_maps_url VARCHAR",
    "ALTER TABLE places ADD COLUMN IF NOT EXISTS last_verified_at TIMESTAMPTZ",
    "ALTER TABLE places ADD COLUMN IF NOT EXISTS utc_offset_minutes INTEGER",
    "ALTER TABLE places ADD COLUMN IF NOT EXISTS region VARCHAR",
    "ALTER TABLE places ADD COLUMN IF NOT EXISTS location_source VARCHAR",
    "ALTER TABLE users ADD COLUMN IF NOT EXISTS quota_period_start TIMESTAMPTZ",
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
    _backfill_regions()


def _backfill_regions() -> None:
    """Fill `region` for places saved before the column existed, parsing the
    state out of their stored address. Cheap, idempotent, no API calls."""
    from sqlalchemy.orm import Session

    from app.models import Place
    from worker.geocode import region_from_address

    try:
        with Session(engine) as db:
            rows = db.scalars(
                select(Place).where(Place.region.is_(None), Place.address.is_not(None))
            ).all()
            for p in rows:
                p.region = region_from_address(p.address)
            db.commit()
    except Exception:  # noqa: BLE001 - never block boot on a best-effort backfill
        pass


@app.get("/health")
def health() -> dict:
    return {"status": "ok", "env": settings.environment}
