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

Dev auto-creates tables on boot. For production, wire Alembic
(`alembic init alembic`) and add a PostGIS `geom` column + GIST index for
"near me" queries (lat/lng floats are the portable source of truth today).
