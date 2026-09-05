"""Pydantic request/response models for the HTTP API."""
from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


class SubmitReelRequest(BaseModel):
    url: str
    # Which map the pins land on; omitted means the caller's personal map.
    map_id: str | None = None


class ReelStatusResponse(BaseModel):
    reel_id: str
    # 'unsupported' = analysed fine, but nothing pinnable in it (an ad, a
    # recipe, a delivery brand). `error` then holds a sentence for the user.
    status: str  # pending | processing | done | failed | unsupported
    place_count: int = 0
    error: str | None = None
    # True when the reel was already analyzed (by this or any user) and the
    # stored result was reused instead of paying for a second analysis.
    already_analyzed: bool = False


class ReelActivityOut(BaseModel):
    reel_id: str
    status: str  # pending | processing | done | failed | unsupported
    platform: str
    title: str | None = None
    thumbnail_url: str | None = None
    place_count: int = 0
    error: str | None = None
    created_at: datetime


class PlaceOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    name: str
    category: str
    cuisine: str | None = None
    lat: float | None = None
    lng: float | None = None
    address: str | None = None
    region: str | None = None
    rating: float | None = None
    review_count: int | None = None
    price_level: int | None = None
    photos: list | None = None
    hours: dict | None = None
    utc_offset_minutes: int | None = None
    phone: str | None = None
    business_status: str | None = None
    google_maps_url: str | None = None
    location_source: str | None = None


class SetPlaceLocationRequest(BaseModel):
    """A hand-placed pin for a place the geocoder couldn't resolve."""

    lat: float = Field(ge=-90, le=90)
    lng: float = Field(ge=-180, le=180)
    address: str | None = None


class UserPlaceOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    place: PlaceOut
    map_id: str
    # Who added it — powers "Priya added Kung Fu Tea" in a shared map.
    added_by_id: str | None = None
    added_by_name: str | None = None
    added_by_color: str | None = None
    city: str | None = None
    reel_url: str | None = None
    description: str | None = None
    tips: list | None = None
    what_to_order: list | None = None
    vibe: list | None = None
    instagram_handle: str | None = None
    website: str | None = None
    hours_hint: str | None = None
    price_level_ai: int | None = None
    confidence: float | None = None
    saved_at: datetime


class CollectionOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    title: str
    category: str | None = None
    city: str | None = None
    place_count: int = 0


class MapOut(BaseModel):
    id: str
    name: str
    emoji: str | None = None
    is_personal: bool
    is_owner: bool
    member_count: int
    place_count: int
    # Only ever returned to the owner.
    invite_code: str | None = None
    created_at: datetime


class CreateMapRequest(BaseModel):
    name: str = Field(min_length=1, max_length=60)
    emoji: str | None = Field(default=None, max_length=8)


class UpdateMapRequest(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=60)
    emoji: str | None = Field(default=None, max_length=8)


class MapInviteOut(BaseModel):
    map_id: str
    invite_code: str
    # Ready to drop into a share sheet.
    invite_url: str


class MapPreviewOut(BaseModel):
    """Shown before sign-in, so it deliberately leaks nothing but the basics."""

    name: str
    emoji: str | None = None
    owner_name: str | None = None
    member_count: int


class MapMemberOut(BaseModel):
    user_id: str
    display_name: str | None = None
    avatar_color: str | None = None
    role: str
    joined_at: datetime


class AppleAuthRequest(BaseModel):
    identity_token: str
    # Apple returns fullName only on the very first authorization, so the
    # client sends it once and the server keeps it.
    display_name: str | None = None
    # One-time code, exchanged for the refresh token we need to revoke Apple's
    # grant when the account is deleted (Guideline 5.1.1(v)).
    authorization_code: str | None = None


class RefreshRequest(BaseModel):
    refresh_token: str


class AuthResponse(BaseModel):
    access_token: str
    refresh_token: str | None = None
    token_type: str = "bearer"


class UserOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    display_name: str | None = None
    avatar_color: str | None = None
    plan: str
    reels_this_month: int
    created_at: datetime


class UpdateMeRequest(BaseModel):
    display_name: str = Field(min_length=1, max_length=60)


class RegisterDeviceRequest(BaseModel):
    apns_token: str
    platform: str = "ios"


# --- Moderation (App Store Guideline 1.2) --------------------------------


class CreateReportRequest(BaseModel):
    target_type: str  # map | user | place
    target_id: str
    reason: str  # offensive | harassment | spam | illegal | other
    note: str | None = Field(default=None, max_length=1000)


class ReportOut(BaseModel):
    id: str
    target_type: str
    target_id: str
    reason: str
    status: str
    created_at: datetime


class CreateBlockRequest(BaseModel):
    user_id: str


class BlockOut(BaseModel):
    user_id: str
    display_name: str | None = None
    avatar_color: str | None = None
    created_at: datetime | None = None
