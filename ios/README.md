# ReelMap iOS

SwiftUI app declared via `project.yml` (XcodeGen) — no hand-edited `pbxproj`.

The project is set up to **build and run on a free Apple ID** (Simulator or your
own iPhone). The paid-only native Instagram share is opt-in (see bottom).

> **Requires iOS 17+** (SwiftData + the SwiftUI `Map` API). Clean, modern material
> UI — no iOS-26-only features. Places/lists are cached locally via SwiftData, so
> the map loads instantly and works offline; a background sync refreshes it.

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
5. There's **no sign-in screen** — the app auto-acquires a dev session on launch
   and lands on the map. Go to the **Add** tab → paste an Instagram reel link →
   **Analyze reel** → watch the **Map** and **Lists** tabs populate.

> Free personal teams re-sign every 7 days — just re-run from Xcode when the app
> stops launching. `NSAllowsArbitraryLoads` is enabled for dev so the device can
> reach your Mac over plain HTTP; remove it before shipping.

### Pasting links into the Add tab
The Add-tab field has a **Paste** button (✕ clears). It reads **both URL and
string** pasteboard payloads — important because Instagram's "Copy link" often
puts a *URL object* on the clipboard, which string-only readers (including a
`String`-typed `PasteButton`) silently miss.

Still not pasting on a real device? Check **Settings → ReelMap → Paste from
Other Apps** and set it to **Allow** — if the iOS paste-permission prompt was
ever declined, all pastes fail silently. In the **Simulator**, host-clipboard
sync must be on: menu bar → **Edit → Automatically Sync Pasteboard**.

## Auth (current)
No login UI for now: on launch the app silently calls the backend's `dev:` auth
(works when `ENVIRONMENT=dev`) and stores the token. Replace `AppState.start()`'s
`dev:me` with real Sign in with Apple when you move to the paid program.

## Structure

| Target | Role |
|---|---|
| `SharedKit` | `Models`, async `APIClient`, `AuthStore` (shared Keychain), `LinkValidator`, `PendingQueue` |
| `ReelMap` | app: `MapScreen`, `CityListsScreen`, `PlaceDetailScreen`, `AddReelScreen`; `Persistence` (SwiftData cache) |
| `ShareExtension` | native share intake: Instagram/TikTok/YouTube → Share → **ReelMap** |

## Share Extension — one-time setup (paid Developer Program)

The extension is **enabled** in `project.yml`. After `xcodegen generate`:
1. In Xcode, open **Signing & Capabilities** for BOTH `ReelMap` and
   `ShareExtension` and confirm the App Group `group.com.yourco.reelmap` is
   checked (with automatic signing, Xcode registers it with your account the
   first time — you may need to tap **+** → App Groups → add that ID once).
2. Build & run the app on your iPhone once (this installs the extension and
   mints the shared session).
3. In Instagram/TikTok/YouTube: **Share → ReelMap**. First time it may live
   under "More" — tap Edit to move it up.

If the backend is unreachable at share time, the link is queued in the App
Group and submitted automatically the next time the app opens.

## Push notifications — one-time setup (paid Developer Program)

Analysis finishes on the server long after the Share Extension has dismissed,
so without push nothing tells you your pins are ready — the app only polls
while it is open in the foreground.

The phone side is wired (`PushManager` + `AppDelegate`): permission is asked
the first time you submit a reel, the device token goes to `POST /devices`, and
tapping a notification opens the Map and refreshes. What's left is credentials:

1. **Apple Developer → Certificates, Identifiers & Profiles → Keys** → **+**,
   tick **Apple Push Notifications service (APNs)**, download the `.p8` **once**
   (it can't be re-downloaded). Note the **Key ID** and your **Team ID**.
2. Put the key somewhere the backend can read it and fill in `backend/.env`:
   ```
   APNS_KEY_PATH=/secrets/AuthKey_ABC123.p8
   APNS_KEY_ID=ABC123XYZ
   APNS_TEAM_ID=YOURTEAMID
   APNS_TOPIC=com.yourco.reelmap     # must equal the app's bundle id
   APNS_USE_SANDBOX=true             # false for TestFlight/App Store builds
   ```
   With any of the first three unset the backend skips push silently, which is
   what you want in local dev.
3. In Xcode, confirm **Signing & Capabilities → Push Notifications** is present
   on the `ReelMap` target (XcodeGen adds the `aps-environment` entitlement).

> **Free personal team?** Push isn't available — signing fails with "Push
> Notifications is not available". Delete the `aps-environment` line from
> `project.yml` and everything else still builds; you just have to open the app
> to see new pins.

> The **Simulator can't receive real APNs pushes.** Test on a physical device,
> or drag a `.apns` file onto the Simulator to fake one.

## Release checklist (before App Store)

- [ ] Deploy the backend behind **HTTPS** (Fly.io/Railway/Render + managed
      Postgres/Redis) and set `API_BASE_URL` to that domain.
- [ ] Remove `NSAllowsArbitraryLoads` from both Info.plist blocks in
      `project.yml` (only needed for plain-HTTP LAN dev).
- [ ] Replace the silent `dev:me` session with **Sign in with Apple**
      (`AppState.start()`), and set `ENVIRONMENT=prod` on the backend so `dev:`
      tokens are rejected.
- [ ] App icon + accent-matched launch screen; App Store screenshots/metadata.
- [ ] Privacy policy URL (App Store requirement — the app sends shared links to
      your server for analysis).
- [ ] Switch `aps-environment` in `project.yml` from `development` to
      `production` (TestFlight/App Store builds use the production APNs
      gateway; a development token silently fails there).
