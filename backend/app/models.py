"""SQLAlchemy ORM models — the canonical Place / per-user UserPlace split.

A reel and its resolved canonical Places are analyzed/geocoded once and shared
across all users (cost lever); each user keeps their own reel-specific context
in UserPlace.

Note: coordinates are stored as plain lat/lng floats for portability (runs on
SQLite for tests, Postgres in prod). A PostGIS `geom` Point column + GIST index
is added later via an Alembic migration for "near me" queries; the floats remain
the source of truth and keep the model database-agnostic.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone

from sqlalchemy import (
    JSON,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    String,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db import Base


def _uuid() -> str:
    return str(uuid.uuid4())


def _now() -> datetime:
    return datetime.now(timezone.utc)


class User(Base):
    __tablename__ = "users"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=_uuid)
    apple_sub: Mapped[str] = mapped_column(String, unique=True, index=True)
    plan: Mapped[str] = mapped_column(String, default="free")  # free | pro
    reels_this_month: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)

    user_places: Mapped[list[UserPlace]] = relationship(back_populates="user")
    devices: Mapped[list[Device]] = relationship(back_populates="user")


class ReelSource(Base):
    """A shared, cached analysis of one Instagram reel (deduped by canonical_id)."""

    __tablename__ = "reel_sources"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=_uuid)
    platform: Mapped[str] = mapped_column(String, default="instagram")
    url: Mapped[str] = mapped_column(String)
    canonical_id: Mapped[str] = mapped_column(String, unique=True, index=True)
    status: Mapped[str] = mapped_column(String, default="pending")  # pending|processing|done|failed
    caption: Mapped[str | None] = mapped_column(String, nullable=True)
    transcript: Mapped[str | None] = mapped_column(String, nullable=True)
    author_handle: Mapped[str | None] = mapped_column(String, nullable=True)
    thumbnail_url: Mapped[str | None] = mapped_column(String, nullable=True)
    summary: Mapped[str | None] = mapped_column(String, nullable=True)
    error: Mapped[str | None] = mapped_column(String, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)
    analyzed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class City(Base):
    __tablename__ = "cities"
    __table_args__ = (UniqueConstraint("name", "country", name="uq_city_name_country"),)

    id: Mapped[str] = mapped_column(String, primary_key=True, default=_uuid)
    name: Mapped[str] = mapped_column(String, index=True)
    country: Mapped[str | None] = mapped_column(String, nullable=True)
    lat: Mapped[float | None] = mapped_column(Float, nullable=True)
    lng: Mapped[float | None] = mapped_column(Float, nullable=True)


class Place(Base):
    """Canonical, geocoded, deduped place (shared across users)."""

    __tablename__ = "places"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=_uuid)
    external_place_id: Mapped[str | None] = mapped_column(String, index=True, nullable=True)
    name: Mapped[str] = mapped_column(String)
    category: Mapped[str] = mapped_column(String, default="other")
    cuisine: Mapped[str | None] = mapped_column(String, nullable=True)
    lat: Mapped[float | None] = mapped_column(Float, nullable=True)
    lng: Mapped[float | None] = mapped_column(Float, nullable=True)
    address: Mapped[str | None] = mapped_column(String, nullable=True)
    # State/province short code ("TX", "NY") — used to label city lists.
    region: Mapped[str | None] = mapped_column(String, nullable=True)
    rating: Mapped[float | None] = mapped_column(Float, nullable=True)
    review_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    price_level: Mapped[int | None] = mapped_column(Integer, nullable=True)
    photos: Mapped[list | None] = mapped_column(JSON, nullable=True)
    hours: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    utc_offset_minutes: Mapped[int | None] = mapped_column(Integer, nullable=True)
    phone: Mapped[str | None] = mapped_column(String, nullable=True)
    business_status: Mapped[str | None] = mapped_column(String, nullable=True)
    google_maps_url: Mapped[str | None] = mapped_column(String, nullable=True)
    last_verified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    city_id: Mapped[str | None] = mapped_column(ForeignKey("cities.id"), nullable=True)

    city: Mapped[City | None] = relationship()


class UserPlace(Base):
    """A user's saved place with the reel-specific context that produced it."""

    __tablename__ = "user_places"
    __table_args__ = (
        UniqueConstraint("user_id", "place_id", "reel_source_id", name="uq_user_place_reel"),
    )

    id: Mapped[str] = mapped_column(String, primary_key=True, default=_uuid)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id"), index=True)
    place_id: Mapped[str] = mapped_column(ForeignKey("places.id"), index=True)
    reel_source_id: Mapped[str] = mapped_column(ForeignKey("reel_sources.id"))
    description: Mapped[str | None] = mapped_column(String, nullable=True)
    tips: Mapped[list | None] = mapped_column(JSON, nullable=True)
    what_to_order: Mapped[list | None] = mapped_column(JSON, nullable=True)
    vibe: Mapped[list | None] = mapped_column(JSON, nullable=True)
    instagram_handle: Mapped[str | None] = mapped_column(String, nullable=True)
    website: Mapped[str | None] = mapped_column(String, nullable=True)
    hours_hint: Mapped[str | None] = mapped_column(String, nullable=True)
    price_level_ai: Mapped[int | None] = mapped_column(Integer, nullable=True)
    sources: Mapped[list | None] = mapped_column(JSON, nullable=True)
    confidence: Mapped[float | None] = mapped_column(Float, nullable=True)
    user_rating: Mapped[float | None] = mapped_column(Float, nullable=True)
    user_notes: Mapped[str | None] = mapped_column(String, nullable=True)
    saved_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)

    user: Mapped[User] = relationship(back_populates="user_places")
    place: Mapped[Place] = relationship()
    reel_source: Mapped[ReelSource] = relationship()


class Collection(Base):
    """Auto-generated city/category list, e.g. 'NYC restaurants'."""

    __tablename__ = "collections"
    __table_args__ = (
        UniqueConstraint("user_id", "city_id", "category", name="uq_collection_scope"),
    )

    id: Mapped[str] = mapped_column(String, primary_key=True, default=_uuid)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id"), index=True)
    city_id: Mapped[str | None] = mapped_column(ForeignKey("cities.id"), nullable=True)
    category: Mapped[str | None] = mapped_column(String, nullable=True)
    title: Mapped[str] = mapped_column(String)
    auto_generated: Mapped[bool] = mapped_column(default=True)


class Device(Base):
    __tablename__ = "devices"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=_uuid)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id"), index=True)
    apns_token: Mapped[str] = mapped_column(String, unique=True)
    platform: Mapped[str] = mapped_column(String, default="ios")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)

    user: Mapped[User] = relationship(back_populates="devices")


class UserReel(Base):
    """Which reels a user submitted — powers the in-app activity/queue feed.

    (ReelSource itself is shared across users; this records who asked for it and
    when, so each user gets their own newest-first history with live status.)
    """

    __tablename__ = "user_reels"
    __table_args__ = (UniqueConstraint("user_id", "reel_source_id", name="uq_user_reel"),)

    id: Mapped[str] = mapped_column(String, primary_key=True, default=_uuid)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id"), index=True)
    reel_source_id: Mapped[str] = mapped_column(ForeignKey("reel_sources.id"), index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)

    reel_source: Mapped[ReelSource] = relationship()
