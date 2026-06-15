# ReelMap

Save travel/food spots from **Instagram Reels** straight to a map. Share a reel
like "Top 5 cafes in NYC" to the app → it analyzes the video, audio, caption, and
on-screen text → extracts every place, geocodes it, and drops a map pin with the
description, tips ("what to order"), photos, and a link back to the reel. Places
auto-organize into city/country lists ("My NYC cafes").

> Full design rationale: see the approved plan referenced in the PR / planning notes.

## Repo layout

```
backend/   FastAPI API + RQ worker pipeline (Python) — the brain
  app/       HTTP API (auth, reels, places/lists), models, config
  worker/    analyze_reel pipeline: fetch → frames → transcribe → Claude → geocode
  tests/     pure-logic unit tests
ios/         SwiftUI app + Share Extension (XcodeGen project.yml)
  SharedKit/      models, API client, shared Keychain auth
  ReelMap/        main app: map, lists, place detail, onboarding
  ShareExtension/ receives the shared reel URL
```

## How it works (the core loop)

1. **Share** an Instagram reel → the iOS **Share Extension** POSTs the URL to `POST /reels`.
2. The API enqueues an async **worker** job and returns immediately.
3. The worker runs **multi-signal extraction** — it fuses caption + on-screen
   text (video frames, read by Claude vision) + `@`venue tags + (optional) audio
   transcript into a structured place list, then geocodes each place.
4. An **APNs push** tells the phone the pins are ready.

**We never store reel videos** — frames/audio are fetched transiently, analyzed,
and discarded. Only derived text/place data + the original reel URL persist.

## Quick start

```bash
# Backend
cd backend
cp .env.example .env            # add ANTHROPIC_API_KEY, APIFY_TOKEN, GOOGLE_PLACES_API_KEY
docker compose up               # Postgres + Redis + API + worker

# Prove the extraction works (no DB needed) — the make-or-break test:
pip install -r requirements.txt
python -m worker.cli --stub     # offline sample reel (needs ANTHROPIC_API_KEY)

# iOS
cd ../ios
brew install xcodegen && xcodegen generate
open ReelMap.xcodeproj          # set your team id + App Group, then run
```

See `backend/README.md` and `ios/README.md` for details.
