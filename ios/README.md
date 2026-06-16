# ReelMap iOS

SwiftUI app declared via `project.yml` (XcodeGen) — no hand-edited `pbxproj`.

The project is set up to **build and run on a free Apple ID** (Simulator or your
own iPhone). The paid-only native Instagram share is opt-in (see bottom).

## Generate & open

```bash
brew install xcodegen
cd ios
xcodegen generate
open ReelMap.xcodeproj
```

## Run it (free account)

1. **Backend up first** (`cd backend && docker compose up`), with
   `REEL_FETCHER=stub` so any link returns the sample reel.
2. **Set the API URL** in `project.yml` → `API_BASE_URL`, then re-run `xcodegen generate`:
   - **Simulator:** `http://localhost:8000` (default).
   - **Physical iPhone:** your Mac's LAN IP, e.g. `http://192.168.1.20:8000`
     (find it: `ipconfig getifaddr en0`). Phone and Mac on the same Wi-Fi.
3. **Signing:** select the `ReelMap` target → Signing & Capabilities → pick your
   Team (a free personal Apple ID works). No special capabilities are required.
4. **Build & Run** on the Simulator or your plugged-in iPhone.
5. In the app: tap **Dev sign in** (DEBUG) → **Add** tab → paste any Instagram
   reel link (or any URL while on `stub`) → **Analyze reel** → watch the **Map**
   and **Lists** tabs populate.

> Free personal teams re-sign every 7 days — just re-run from Xcode when the app
> stops launching. `NSAllowsArbitraryLoads` is enabled for dev so the device can
> reach your Mac over plain HTTP; remove it before shipping.

## How testing differs from production
- **Login:** the **Dev sign in** button calls the backend's `dev:` auth (works
  when `ENVIRONMENT=dev`). Real Sign in with Apple needs the paid program.
- **Adding reels:** the **Add tab** (paste a link) replaces the native share
  sheet and exercises the exact same backend pipeline.

## Structure

| Target | Role |
|---|---|
| `SharedKit` | `Models`, async `APIClient`, `AuthStore` (Keychain) |
| `ReelMap` | app: `MapScreen`, `CityListsScreen`, `PlaceDetailScreen`, `AddReelScreen`, `OnboardingView` |
| `ShareExtension` | (paid only) native Instagram share intake — disabled by default |

## Enabling the Share Extension (paid Apple Developer Program)

When you have the $99/yr program and an App Group:
1. In `project.yml`, uncomment the `ShareExtension` target, and add back to the
   `ReelMap` target: the `entitlements` block (App Group + `applesignin` +
   `aps-environment`) and an `embed: true` dependency on `ShareExtension`.
2. Create the App Group `group.com.yourco.reelmap` in the Apple Developer portal
   and enable it on both targets.
3. Set `AuthStore.useSharedAccessGroup = true` so the extension and app share one
   session.
4. `xcodegen generate` again. Now Instagram → Share → ReelMap works natively.
