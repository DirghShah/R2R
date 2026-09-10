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

    # The dev sign-in shortcut — POST /auth/apple with {"identity_token":
    # "dev:anyone"} — skips Apple entirely and mints a session for any id you
    # name. It used to be gated on `environment`, which defaults to "dev": a
    # deploy that forgot to set ENVIRONMENT was silently wide open, and nothing
    # about a healthy-looking service would have told you. Its own flag,
    # defaulting to off, fails closed instead.
    allow_dev_sign_in: bool = False

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
    # Production sets this explicitly (currently claude-haiku-4-5). The default
    # matters only when the variable is missing, so it should be the current
    # flagship rather than a superseded one — an unset variable landing on a
    # previous-generation model is a silent downgrade nobody would notice.
    anthropic_model: str = "claude-opus-5"

    # --- Reel fetching (Instagram) ---
    reel_fetcher: str = "apify"  # apify | ytdlp | stub
    # When the primary fetcher fails, try yt-dlp before giving up. Different
    # failure mode (local extractor vs hosted service), so the two rarely break
    # together — which is the only reason to carry both.
    fetcher_fallback: bool = True
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
    # Rough $/place for the cost log. Two billed calls: Text Search Pro (~$0.032)
    # to find and verify the venue, plus Place Details Enterprise (~$0.035) for
    # rating, photos and hours. `rating` alone is what lifts Details to the
    # Enterprise tier — Google prices a call by its most expensive field.
    google_cost_per_search: float = 0.032
    google_cost_per_enrichment: float = 0.035
    google_cost_per_place: float = 0.067

    # --- Not paying twice for the same restaurant ---
    # Look for a canonical place we already resolved before calling anyone. Food
    # reels cluster hard on the same venues, so the same restaurant arrives over
    # and over from different people, and every arrival used to be a fresh pair
    # of billed lookups.
    place_cache_enabled: bool = True
    # Deliberately stricter than place_auto_accept_threshold (0.85). A wrong
    # cache hit silently merges two different restaurants for everyone, forever,
    # which is far worse than paying for one more lookup.
    place_cache_min_similarity: float = 0.92
    # How long to remember that a name found nothing, so a viral reel naming a
    # venue Google doesn't know isn't re-searched by every person who shares it.
    # Bounded because Google does add places.
    geocode_miss_ttl_days: int = 30

    # --- Enrich when someone looks, not when we pin ---
    # The scorer that decides *which* venue is right reads only Text Search
    # fields, so Place Details buys nothing at analysis time — it is rating,
    # photos and hours, which matter only once a person opens the place. With
    # this on, pins cost one call instead of two and the rest is fetched on
    # first open.
    #
    # Off by default: turning it on without an app that requests enrichment
    # leaves places with no rating or photos. Flip it once build 10 is out.
    lazy_place_enrichment: bool = False
    # Re-enrich on open when the stored data is older than this. Hours and
    # ratings go stale, and today a place enriched once keeps its opening hours
    # forever.
    place_enrichment_stale_days: int = 30

    # What the thing costs to exist, as opposed to what each reel costs. Per-reel
    # spend is currently a rounding error next to hosting, so a cost view that
    # only counts reels answers the wrong question. JSON so it can be edited on
    # the platform without a deploy: a list of
    # {"name": str, "usd": float, "period": "monthly" | "annual" | "once"}.
    # Annual and one-off entries are amortised to a month where a monthly total
    # is what's wanted.
    fixed_costs: str = (
        '[{"name": "Railway Hobby", "usd": 5.0, "period": "monthly"},'
        ' {"name": "Apple Developer Program", "usd": 99.0, "period": "annual"},'
        ' {"name": "noshmap.app domain", "usd": 20.0, "period": "annual"}]'
    )

    def fixed_cost_items(self) -> list[dict]:
        """Parsed `fixed_costs`, never raising — a malformed override must not
        take down the stats endpoint, and an empty list reads as "none set"."""
        import json

        try:
            items = json.loads(self.fixed_costs)
        except (ValueError, TypeError):
            return []
        if not isinstance(items, list):
            return []
        out = []
        for item in items:
            if not isinstance(item, dict):
                continue
            try:
                usd = float(item.get("usd", 0))
            except (TypeError, ValueError):
                continue
            period = str(item.get("period", "monthly")).lower()
            if period not in {"monthly", "annual", "once"}:
                period = "monthly"
            out.append({"name": str(item.get("name", "unnamed")), "usd": usd,
                        "period": period})
        return out

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
