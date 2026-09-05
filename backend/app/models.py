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
    # Apple returns fullName only on the very first authorization and never in
    # the identity token, so the client sends it once and we keep it.
    display_name: Mapped[str | None] = mapped_column(String, nullable=True)
    # Deterministic per-user colour for initial avatars — no upload, no storage,
    # no moderation surface.
    avatar_color: Mapped[str | None] = mapped_column(String, nullable=True)
    # Apple refresh token, needed to revoke our access on account deletion
    # (App Store Guideline 5.1.1(v)).
    apple_refresh_token: Mapped[str | None] = mapped_column(String, nullable=True)
    plan: Mapped[str] = mapped_column(String, default="free")  # free | pro
    reels_this_month: Mapped[int] = mapped_column(Integer, default=0)
    # Which calendar month `reels_this_month` is counting. Without it the
    # counter only ever climbs and eventually locks the user out for good.
    quota_period_start: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)

    user_places: Mapped[list[UserPlace]] = relationship(back_populates="user")
    devices: Mapped[list[Device]] = relationship(back_populates="user")


class Map(Base):
    """A collection of saved places, owned by one user and shared with others.

    A personal map and a shared map are the *same object* — sharing is just
    adding a member — so there is one code path rather than an `is_shared`
    branch running through everything.
    """

    __tablename__ = "maps"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=_uuid)
    name: Mapped[str] = mapped_column(String)
    emoji: Mapped[str | None] = mapped_column(String, nullable=True)
    owner_id: Mapped[str] = mapped_column(ForeignKey("users.id"), index=True)
    # The auto-created map every user gets on sign-up. Can't be deleted —
    # there always has to be somewhere for a share to land.
    is_personal: Mapped[bool] = mapped_column(default=False)
    # Null until the owner shares it. Rotating this invalidates old links.
    invite_code: Mapped[str | None] = mapped_column(String, unique=True, index=True, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)

    members: Mapped[list[MapMember]] = relationship(
        back_populates="map", cascade="all, delete-orphan"
    )


class MapMember(Base):
    """Membership *is* the relationship — there is no friend graph."""

    __tablename__ = "map_members"
    __table_args__ = (UniqueConstraint("map_id", "user_id", name="uq_map_member"),)

    id: Mapped[str] = mapped_column(String, primary_key=True, default=_uuid)
    map_id: Mapped[str] = mapped_column(ForeignKey("maps.id"), index=True)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id"), index=True)
    role: Mapped[str] = mapped_column(String, default="editor")  # owner | editor
    joined_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)

    map: Mapped[Map] = relationship(back_populates="members")
    user: Mapped[User] = relationship()


class RefreshToken(Base):
    """Long-lived, rotating session token.

    The access JWT is short-lived, but the Share Extension can never show
    sign-in UI — so it needs a way to re-authenticate without the user. Hence a
    refresh token rather than simply a longer JWT.

    Only the hash is stored: a leaked database dump must not hand over live
    sessions.
    """

    __tablename__ = "refresh_tokens"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=_uuid)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id"), index=True)
    token_hash: Mapped[str] = mapped_column(String, unique=True, index=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)


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
    # When the current run started. A worker that dies mid-job leaves
    # status="processing" forever, and without this there is no way to tell a
    # stuck reel from one that is legitimately still working.
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
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
    # "user" once someone has placed the pin by hand; the geocoder never
    # overwrites a hand-placed location on re-analysis.
    location_source: Mapped[str | None] = mapped_column(String, nullable=True)
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
        # One venue is exactly one pin per map, whichever member added it and
        # however many reels it came from.
        UniqueConstraint("map_id", "place_id", name="uq_map_place"),
    )

    id: Mapped[str] = mapped_column(String, primary_key=True, default=_uuid)
    map_id: Mapped[str] = mapped_column(ForeignKey("maps.id"), index=True)
    # Who added it — powers "Priya added Kung Fu Tea" in a shared map.
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


class Report(Base):
    """A user reporting objectionable content or behaviour.

    Required by App Store Guideline 1.2: an app with user-generated content
    must let people flag it. The surfaces that carry user content here are map
    names, display names, and the places someone adds to a shared map.

    Reports are stored rather than emailed so there is a reviewable record —
    Apple asks how reports are handled, and "we read an inbox" is a weaker
    answer than a queue with a status on each row.
    """

    __tablename__ = "reports"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=_uuid)
    reporter_id: Mapped[str] = mapped_column(ForeignKey("users.id"), index=True)
    # "map" | "user" | "place"
    target_type: Mapped[str] = mapped_column(String)
    target_id: Mapped[str] = mapped_column(String, index=True)
    reason: Mapped[str] = mapped_column(String)
    note: Mapped[str | None] = mapped_column(String, nullable=True)
    # "open" | "actioned" | "dismissed"
    status: Mapped[str] = mapped_column(String, default="open")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)


class Block(Base):
    """One user blocking another.

    Blocking hides the blocked person's places and their row in member lists,
    for the blocker only. It deliberately does not remove anyone from a map:
    the owner decides membership, and a block that silently ejected people
    would be a griefing tool.
    """

    __tablename__ = "blocks"
    __table_args__ = (UniqueConstraint("user_id", "blocked_user_id", name="uq_block_pair"),)

    id: Mapped[str] = mapped_column(String, primary_key=True, default=_uuid)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id"), index=True)
    blocked_user_id: Mapped[str] = mapped_column(ForeignKey("users.id"), index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)
