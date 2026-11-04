# Backlog

Things worth doing that aren't blocking a release. Kept here so they stop
living in chat scrollback.

---

## Rename ReelMap → Nosh

The app, the website and the App Store listing all say Nosh. The Xcode target,
the project file, the source folder and a handful of strings still say ReelMap,
so `git pull && open Nosh.xcodeproj` fails for anyone following the obvious
instruction.

Attempted once and reverted — not because it broke, but because it landed in
the middle of shipping a crash fix, and a mechanical rename that cannot be
compiled here is a bad thing to put in front of a release that users need.

### Safe to rename

- `ios/ReelMap/` → `ios/Nosh/` (use `git mv`, it keeps the history)
- `project.yml`: `name:`, the app target, `sources:`, the entitlements path,
  and **`path: ReelMap/Info.plist` at line 90** — that one is easy to miss and
  breaks the build rather than failing loudly
- `ReelMapApp.swift` → `NoshApp.swift`, `struct ReelMapApp` → `struct NoshApp`
- `ios/check.py` → `TARGETS = ["Nosh", "SharedKit", "ShareExtension"]`
- `.gitignore` paths
- `main.py`'s FastAPI title and startup log line
- `extract.py`'s prompt sentence ("ReelMap pins places on a map")
- README prose in the repo root, `ios/`, `backend/`, `web/`, and CLAUDE.md
- The scheme comment in `project.yml`, which currently explains why the target
  was *not* renamed

### Must NOT be renamed

| Identifier | Why |
|---|---|
| `com.yourco.reelmap` and the `.share` / `.SharedKit` suffixes | Permanent once an App Store listing exists. Changing it means a new app record, new builds, re-uploaded screenshots — a new app, not a rename |
| `group.com.yourco.reelmap` | Backs the App Group and the shared keychain. Change it and every installed user is signed out and loses their cache, and the share extension stops seeing the session |
| `keychain-access-groups` | Same |
| `reelmap://` deep links (`pipeline.py:652,678`, the URL scheme) | Invite links and push payloads already sent out use it. Universal links through noshmap.app keep working, but the custom scheme has to stay registered |
| Postgres user/db in `docker-compose.yml` and `.env.example` | Local dev only, invisible, and renaming it orphans anyone's existing volume. Cosmetic churn with a real failure mode |

Do it right after a release ships, never before one, and build in Xcode before
pushing — `check.py` cannot catch a wrong path in `project.yml`.

---

## Smaller items

- **Run `scripts/backfill_pins.py`** — places saved 10–30 Oct still have no
  coordinates and are invisible on the map. Dry run, then `--apply`
- **Test `claude-haiku-5-5`** — roughly 90% cheaper than the current
  `claude-haiku-4-5` ($0.10/$0.50 against $1/$5). Measure extraction quality on
  a few reels before committing; accuracy is what makes the app worth using
- **Round location to 2dp** before sending to `/places/suggest`, so the
  "Coarse Location" privacy label is unambiguous rather than merely defensible
- **Vendor canary** — one daily call each to Anthropic, Google Places and
  Apify, alerting on failure. All three have now died silently: Google on 10
  Oct, Anthropic around 13 Oct, and each was found by a user noticing, not by
  us
- **Raise `RATE_LIMIT_REELS_PER_HOUR`** (currently 20) if testing keeps
  tripping it
