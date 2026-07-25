"""Pydantic request/response models for the HTTP API."""
from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict


class SubmitReelRequest(BaseModel):
    url: str


class ReelStatusResponse(BaseModel):
    reel_id: str
    status: str  # pending | processing | done | failed
    place_count: int = 0
    error: str | None = None


class ReelActivityOut(BaseModel):
    reel_id: str
    status: str  # pending | processing | done | failed
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


class UserPlaceOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    place: PlaceOut
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


class AppleAuthRequest(BaseModel):
    identity_token: str


class AuthResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"


class RegisterDeviceRequest(BaseModel):
    apns_token: str
    platform: str = "ios"
