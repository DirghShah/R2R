# ReelMap iOS

SwiftUI app + Share Extension. The project is declared in `project.yml`
(XcodeGen) so the `.xcodeproj` generates deterministically — no hand-edited
`pbxproj`.

## Generate & open

```bash
brew install xcodegen
xcodegen generate
open ReelMap.xcodeproj
```

## Before first run

1. **Signing:** set `DEVELOPMENT_TEAM` in `project.yml` (or each target in Xcode).
2. **Bundle ids:** defaults are `com.yourco.reelmap[.share|.SharedKit]` — change
   the `bundleIdPrefix` to your own.
3. **App Group:** `group.com.yourco.reelmap` must exist in your Apple Developer
   account and be enabled on both the app and the Share Extension (it backs the
   shared Keychain session + the offline pending-share queue).
4. **Capabilities:** Sign in with Apple (app) and Push Notifications (app).
5. **API base URL:** set `API_BASE_URL` (build setting in `project.yml`) to your
   backend — `http://localhost:8000` for the simulator against a local backend.

## Structure

| Target | Role |
|---|---|
| `SharedKit` | `Models`, `APIClient`, `AuthStore` (shared Keychain) — used by app + extension |
| `ReelMap` | app shell: `MapScreen`, `CityListsScreen`, `PlaceDetailScreen`, `OnboardingView` |
| `ShareExtension` | extracts the shared reel URL → `APIClient.submitReel`, with an offline fallback queue |

## Flow

Onboarding (Sign in with Apple) → JWT in shared Keychain → share a reel from
Instagram → extension submits URL → app polls / receives push → `MapScreen`
renders pins; `PlaceDetailScreen` shows tips + **Open in Instagram / Google Maps
/ Apple Maps**.

## Notes

- Server is the source of truth; add a SwiftData cache layer (planned) for
  offline/instant launch — the screens already read through `PlacesStore`, so it
  drops in behind that.
- Requires Xcode 15+ / iOS 17 (uses the SwiftUI `Map` API and `ContentUnavailableView`).
