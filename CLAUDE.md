# CLAUDE.md — ReelMap

Context + handoff for Claude Code working in this repo locally.

## What this is
A Mio-style iOS app: share an **Instagram reel** → backend analyzes it (caption +
on-screen text via Claude vision + optional audio) → extracts places → geocodes
them → drops **map pins** with tips/photos/reel link → auto-groups into city lists.
We never store reel videos (frames/audio fetched transiently, then discarded).

Full design lives in `README.md`, `backend/README.md`, `ios/README.md`.

## Repo layout
- `backend/` — FastAPI API + RQ worker (Python). The brain.
  - `worker/extract.py` — **the core**: multi-signal fusion → Claude structured output.
  - `worker/pipeline.py` — async job: fetch → frames → transcribe → extract → geocode → persist → push.
  - `worker/fetchers/` — swappable reel fetchers (`stub`, `apify`; yt-dlp later).
  - `app/` — HTTP API (auth, reels, places/lists), SQLAlchemy models, config.
- `ios/` — SwiftUI app + Share Extension, declared via `project.yml` (XcodeGen).

## Current status (verified)
- Backend: 7 unit tests + full API smoke flow pass. All modules import; tables build.
- Extraction engine validated against the stub sample reel with Haiku.
- iOS: sources written but **never compiled** (no macOS in the build env) — expect
  minor first-build fixups. No `.xcodeproj` committed; generate it with XcodeGen.

## Active branch
`claude/bold-maxwell-2d4wya` — keep developing here; don't push to other branches.

## Local setup
1. `backend/.env` (copy from `.env.example`). Current intended dev values:
   ```
   ANTHROPIC_API_KEY=sk-ant-...
   ANTHROPIC_MODEL=claude-haiku-4-5   # cheap model for now
   REEL_FETCHER=stub                  # sample reel; switch to apify for real reels
   GEOCODER=nominatim                 # free; switch to google for photos/ratings
   ```
2. Validate the engine with no infra:
   ```
   cd backend && python3 -m venv .venv && source .venv/bin/activate
   pip install -r requirements.txt
   python -m worker.cli --stub
   ```
3. Full stack (needs Docker Desktop running): `cd backend && docker compose up --build`
   - Health: http://localhost:8000/health · Docs: http://localhost:8000/docs

## Next steps (in order)
1. Get the full backend up (Docker, or ask to add a no-Docker SQLite+inline dev mode).
2. Run a reel end-to-end via `/docs` or curl: dev sign-in (`{"identity_token":"dev:me"}`)
   → POST /reels → poll GET /reels/{id} → GET /places, /lists. With `stub` this needs
   only the Anthropic key.
3. Add `APIFY_TOKEN` (+ `REEL_FETCHER=apify`) to test real reels; add
   `GOOGLE_PLACES_API_KEY` (+ `GEOCODER=google`) for better pins.
4. iOS: `cd ios && xcodegen generate`, set signing/App Group, point `API_BASE_URL`
   at the backend, build on a real device to test the share flow.

## Conventions / guardrails
- Claude model is config-driven (`ANTHROPIC_MODEL`); default in code is opus, dev uses haiku.
- Keep the reel-fetch logic behind the `ReelFetcher` interface — it's the fragile/ToS part.
- Don't persist reel videos. Only derived text/place data + the reel URL.
- Run `pytest` in `backend/` before committing backend changes.
