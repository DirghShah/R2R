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
    # Guards GET /admin/stats. Unset means the endpoint 404s — which is the
    # right default, since an ops view that exists by accident is a leak.
    admin_token: str | None = None

    jwt_secret: str = "dev-only-change-me"
    jwt_algorithm: str = "HS256"
    # Short-lived access token; the refresh token carries the session.
    jwt_expiry_hours: int = 24
    refresh_token_days: int = 365
    apple_client_secret_ttl_minutes: int = 30
    apple_bundle_id: str = "com.yourco.reelmap"
    # Needed only to revoke Apple tokens on account deletion (Guideline
    # 5.1.1(v)). Same key family as APNs but a *Sign in with Apple* key.
    apple_team_id: str | None = None
    apple_key_id: str | None = None
    apple_private_key: str | None = None  # base64 of the .p8

    # --- Invite links ---
    # Public origin of this API; invite URLs are built from it.
    public_base_url: str = "http://localhost:8000"
    app_store_url: str = ""

    # --- AI / pipeline ---
    anthropic_api_key: str | None = None
    anthropic_model: str = "claude-opus-4-8"

    # --- Reel fetching (Instagram) ---
    reel_fetcher: str = "apify"  # apify | ytdlp | stub
    apify_token: str | None = None
    apify_actor: str = "apify/instagram-scraper"           # instagram
    apify_actor_tiktok: str = "clockworks/tiktok-scraper"  # tiktok
    apify_actor_youtube: str = "streamers/youtube-scraper"  # youtube shorts
    apify_cost_per_reel: float = 0.005  # rough estimate ($/reel) for the cost log

    # A reel stuck in pending/processing for longer than this is treated as
    # abandoned and re-queued. Analysis normally takes 15-60s; the gap is
    # generous so a slow reel is never re-run while it's still working.
    stale_reel_minutes: int = 15

    # --- What we're willing to pin ---
    # Reels that aren't recommendations of visitable venues (meal-kit ads,
    # recipe videos, product promos) are rejected outright before geocoding —
    # they cost money and put junk pins on people's maps.
    #
    # Beyond that, only places in these categories are kept. The extractor can
    # emit `hotel`, `sight`, `event` and `club` too; they're excluded by default
    # because this is a food-and-drink app. Widen the list here (or set
    # ALLOWED_PLACE_CATEGORIES) if that changes — nothing else needs touching.
    allowed_place_categories: str = "cafe,restaurant,bar"

    @property
    def allowed_categories(self) -> set[str]:
        return {c.strip().lower() for c in self.allowed_place_categories.split(",") if c.strip()}

    # --- Geocoding ---
    google_places_api_key: str | None = None
    geocoder: str = "nominatim"  # nominatim (free, default) | google (photos/ratings)
    google_places_region: str = "US"
    google_places_language: str = "en"
    # Candidate-scoring acceptance for Google Places: take the top match only when
    # it scores well and clearly beats the runner-up; below the floor -> no pin
    # (never auto-accept a bad first result).
    place_auto_accept_threshold: float = 0.85
    place_min_margin_over_second: float = 0.15
    place_min_score: float = 0.55  # below this, leave un-pinned rather than mispin
    # Rough $/place for the cost log (Text Search Pro + one Place Details Enterprise).
    google_cost_per_place: float = 0.05

    # --- Transcription ---
    enable_transcription: bool = True
    whisper_model: str = "small"

    # --- Free-tier usage cap (monetization hook) ---
    # A reel with 5 places costs ~$0.27 (Google Places dominates at $0.05/place),
    # so this number is a direct monthly liability per free user. Keep it small
    # until there's a paid tier to fund it.
    free_monthly_reel_limit: int = 50

    # --- Abuse protection (a public URL is a direct line to the AI/geo bill) ---
    rate_limit_reels_per_hour: int = 20
    rate_limit_auth_per_hour: int = 30
    # Browsers never call this API (native app only), so the allowlist stays
    # empty unless something explicitly needs it.
    cors_allow_origins: list[str] = []

    # --- Push (APNs) ---
    # Either a path (local dev) or the base64 of the .p8 (Railway/Fly, where
    # secrets are env vars and there is no file to point at).
    apns_key_path: str | None = None
    apns_key_content: str | None = None
    apns_key_id: str | None = None
    apns_team_id: str | None = None
    apns_topic: str = "com.yourco.reelmap"
    apns_use_sandbox: bool = True


@lru_cache
def get_settings() -> Settings:
    s = Settings()
    # Managed Postgres (Railway/Heroku/Render) hands out "postgres://", a scheme
    # SQLAlchemy 2.x rejects outright. Normalising here turns a confusing
    # first-deploy crash into a non-event.
    if s.database_url.startswith("postgres://"):
        s.database_url = s.database_url.replace("postgres://", "postgresql+psycopg2://", 1)
    elif s.database_url.startswith("postgresql://"):
        s.database_url = s.database_url.replace("postgresql://", "postgresql+psycopg2://", 1)
    return s


settings = get_settings()
