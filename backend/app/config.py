"""Application configuration, loaded from environment variables.

Every setting has a dev-friendly default so the app can boot locally with an
empty .env, but production secrets (Anthropic key, Apify token, Google Places
key, Apple/APNs credentials) must be supplied via the environment.
"""
from __future__ import annotations

from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    # --- Core ---
    environment: str = "dev"
    database_url: str = "postgresql+psycopg2://reelmap:reelmap@localhost:5432/reelmap"
    redis_url: str = "redis://localhost:6379/0"

    # --- Auth ---
    jwt_secret: str = "dev-only-change-me"
    jwt_algorithm: str = "HS256"
    jwt_expiry_hours: int = 24 * 30
    apple_bundle_id: str = "com.yourco.reelmap"

    # --- AI / pipeline ---
    anthropic_api_key: str | None = None
    anthropic_model: str = "claude-opus-4-8"

    # --- Reel fetching (Instagram) ---
    reel_fetcher: str = "apify"  # apify | ytdlp | stub
    apify_token: str | None = None
    apify_actor: str = "apify/instagram-scraper"

    # --- Geocoding ---
    google_places_api_key: str | None = None
    geocoder: str = "nominatim"  # nominatim (free, default) | google (photos/ratings)

    # --- Transcription ---
    enable_transcription: bool = True
    whisper_model: str = "small"

    # --- Free-tier usage cap (monetization hook; generous while free) ---
    free_monthly_reel_limit: int = 1000

    # --- Push (APNs) ---
    apns_key_path: str | None = None
    apns_key_id: str | None = None
    apns_team_id: str | None = None
    apns_topic: str = "com.yourco.reelmap"
    apns_use_sandbox: bool = True


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
