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

Production `.env` must set: `ENVIRONMENT=prod`, a real `JWT_SECRET`,
`DATABASE_URL`, `REDIS_URL`, the vendor keys, and `APNS_KEY_CONTENT` (base64 of
the .p8 — a *path* has no meaning on a PaaS).

**Never set `ALLOW_DEV_SIGN_IN` on a deployed service.** It makes
`{"identity_token": "dev:anyone"}` a valid sign-in for any account id you name,
which is the whole authentication system bypassed. It defaults to off, so
production is safe by doing nothing; local development and the test suite turn
it on explicitly. It used to key off `ENVIRONMENT`, which defaults to `dev` —
one forgotten variable on a new deploy left it wide open, and nothing about a
healthy-looking service would have shown it.

### Vibe search

`POST /places/search` finds saved places by what they feel like — "somewhere
quiet I can work", "impressive but not stuffy". The name filter in the app stays
instant and offline; this runs only when someone submits, because it is a model
call.

No embeddings and no vector store. A person's saved places number in the tens or
low hundreds, so the whole candidate set fits in one prompt, and a model that
can read the descriptions beats cosine similarity over them. It also means no
second vendor and no index to keep in sync.

Two things it must get right, both covered by tests: ids returned by the model
are checked against the ids that went in, because a model asked for an
identifier will occasionally invent one; and an empty result is a real answer,
since a wrong match teaches people the search doesn't work.

The ceiling is the data. It can only find what a reel actually said, which is
why `vibe` is a closed list (`worker/extract.py:VIBES`) — free text gave one
idea three spellings and nothing matched anything.

Scoped to one map by default: that is what people mean when they search while
looking at a map, and every candidate place is part of the prompt, so scope is
also the cost control. `VIBE_SEARCH_MAX_PLACES` is the backstop.

### Cost control

Two Google calls used to run for every extracted place, every time. Three
changes cut that:

- **The place cache.** Before any external lookup, `_cached_place` looks for a
  canonical place already resolved in the same city. Food reels cluster on the
  same venues, so the same restaurant arrives repeatedly. Deliberately strict —
  same category, same city, name similarity above `PLACE_CACHE_MIN_SIMILARITY`
  (0.92, higher than the 0.85 used to accept a Google candidate) — because a
  wrong hit merges two restaurants permanently, for everyone.
- **The miss cache.** A name that found nothing is remembered for
  `GEOCODE_MISS_TTL_DAYS`, so a viral reel naming an unknown venue isn't
  re-searched by every person who shares it. Bounded, because Google adds places.
- **`LAZY_PLACE_ENRICHMENT`.** Off by default. On, a pin costs one Text Search
  instead of a search plus a Place Details call; rating, photos and hours are
  fetched by `POST /places/{id}/enrich` when someone opens the place. Safe
  because the scorer that decides *which* venue is right reads only search
  fields — Details buys nothing at analysis time. **Do not turn this on until
  an app that calls the enrich endpoint is live**, or places will show with no
  rating or photos.



A reel with 5 places costs roughly **$0.27** — Apify $0.005, Google Places
5 x $0.05, Claude ~$0.02. Google Places dominates. `_log_metrics` prints the
real per-reel cost to the worker log.

Two guards, both on by default:
- `FREE_MONTHLY_REEL_LIMIT` (default 50) caps the monthly liability per user.
- `RATE_LIMIT_REELS_PER_HOUR` (default 20) caps bursts. Backed by Redis so it
  holds across replicas, and fails **open** if Redis is down.


## Starting from a clean state

`scripts/reset_data.py` deletes every row and keeps the schema. Irreversible,
and it deletes *everyone's* data, not just yours.

```bash
python -m scripts.reset_data          # dry run — prints what would go
python -m scripts.reset_data --yes    # dev
python -m scripts.reset_data --yes --i-understand-this-is-production
```

Against Railway, run it through the CLI so it uses the deployed database:

```bash
npm i -g @railway/cli && railway login
railway link                          # pick the project, then the R2R service
railway run python -m scripts.reset_data          # dry run first
railway run python -m scripts.reset_data --yes --i-understand-this-is-production
```

**What it costs.** Deleting `reel_sources` drops the shared analysis cache. A
reel that was already analysed is normally free to re-add; afterwards every
reel is a fresh paid run (~$0.27 with 5 places, most of it Google Places).

**Afterwards.** Every device is signed in as a user that no longer exists, so
the app 401s, fails to refresh and shows the sign-in screen. Signing in with
the same Apple ID creates a fresh account and a new personal map — Apple
returns the same subject id, so nothing needs reinstalling. The local SwiftData
cache self-heals on the next sync.
