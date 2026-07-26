# ReelMap backend

FastAPI API + an RQ worker that runs the reel→places pipeline.

## Run

```bash
cp .env.example .env     # fill in keys (see below)
docker compose up        # db (Postgres/PostGIS) + redis + api + worker
# API: http://localhost:8000  ·  docs: http://localhost:8000/docs
```

Local (no Docker):

```bash
pip install -r requirements.txt
uvicorn app.main:app --reload                 # API
rq worker --url redis://localhost:6379/0 reels  # worker (separate shell)
```

## Required keys (`.env`)

| Var | Purpose |
|---|---|
| `ANTHROPIC_API_KEY` | Claude extraction (required for real analysis) |
| `APIFY_TOKEN` | Instagram reel fetch via Apify actor |
| `GOOGLE_PLACES_API_KEY` | geocoding + place enrichment |
| `APNS_*` | push notifications (optional in dev) |

Set `REEL_FETCHER=stub` and `GEOCODER=nominatim` to run without vendor keys.

## The make-or-break test

Validates the whole extraction core (multi-signal fusion → structured JSON)
without DB, queue, or app:

```bash
python -m worker.cli --stub                                   # offline sample reel
python -m worker.cli https://www.instagram.com/reel/XXXX/     # real reel (needs APIFY_TOKEN)
python -m worker.cli https://www.instagram.com/reel/XXXX/ --transcribe  # + Whisper
```

It prints the validated `ReelExtraction` JSON. Gate everything else on this
producing good places for: (a) caption-complete reels, (b) **music-only** reels
(proves the on-screen-text vision path), (c) voiceover reels.

## Tests

```bash
pytest            # pure-logic tests (no network/keys)
```

## Pipeline (`worker/pipeline.py::analyze_reel`)

`fetch (worker/fetchers) → sample scene-change frames (frames.py) →
transcribe if speech (transcribe.py) → fuse + extract via Claude (extract.py) →
geocode + enrich (geocode.py) → persist canonical Place + per-user UserPlace +
auto Collection → APNs push`.

The fetch step is behind a swappable `ReelFetcher` (`REEL_FETCHER`) — Apify for
MVP, yt-dlp later — so the fragile/ToS-sensitive part is isolated.

## Migrations

The schema is owned by **Alembic in every environment** — there is no
`create_all` fallback, because it only ran in dev and left production with no
tables at all.

```bash
alembic upgrade head                      # apply
alembic revision --autogenerate -m "..."  # after changing app/models.py
alembic current                           # what's applied
```

`entrypoint.sh` runs `alembic upgrade head` before starting the API or worker,
so a deploy migrates itself.

**Adopting this on an existing dev database** (one that already has tables from
the old `create_all` path):

```bash
alembic stamp head    # "these migrations are already applied" — do NOT upgrade
```

Running `upgrade` on such a database would try to re-create existing tables and
fail. Stamp first, once.

Later: a PostGIS `geom` column + GIST index for "near me" queries (lat/lng
floats remain the portable source of truth).

## Deploying

Container + managed Postgres + managed Redis. `api` and `worker` are the same
image with different commands — exactly what `docker-compose.yml` describes.

Recommended: **Railway** (reads the Dockerfile, Postgres/Redis are plugins).
Fly.io works too. Avoid free tiers that sleep — a sleeping worker stalls
analysis mid-job.

Production `.env` must set: `ENVIRONMENT=prod` (this rejects `dev:` auth
tokens), a real `JWT_SECRET`, `DATABASE_URL`, `REDIS_URL`, the vendor keys, and
`APNS_KEY_CONTENT` (base64 of the .p8 — a *path* has no meaning on a PaaS).

### Cost control

A reel with 5 places costs roughly **$0.27** — Apify $0.005, Google Places
5 x $0.05, Claude ~$0.02. Google Places dominates. `_log_metrics` prints the
real per-reel cost to the worker log.

Two guards, both on by default:
- `FREE_MONTHLY_REEL_LIMIT` (default 50) caps the monthly liability per user.
- `RATE_LIMIT_REELS_PER_HOUR` (default 20) caps bursts. Backed by Redis so it
  holds across replicas, and fails **open** if Redis is down.
