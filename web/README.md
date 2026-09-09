# Nosh — marketing site

Astro, deployed to Vercel from this subdirectory. Zero JS shipped except ~50
lines of hand-written scroll code; no CSS framework.

```bash
npm install
npm run dev      # http://localhost:4321
npm run build
```

## Deploying

New Vercel project → import this repo → **Root Directory: `web`**. Framework
preset auto-detects as Astro. Nothing else to configure; `vercel.json` is picked
up automatically.

## The one thing that must be verified after every deploy

`vercel.json` proxies two paths to the Railway backend:

| Path | Why it can't be static |
|---|---|
| `/join/:code` | Renders map name, owner and member count from Postgres |
| `/.well-known/apple-app-site-association` | iOS decides whether links open the app; must come from **this** origin with **no redirect** |

These are *rewrites*, not redirects — a redirect silently breaks Universal
Links, with no error anywhere to explain why.

`vercel.json` cannot explain this itself: JSON has no comments, and Vercel
rejects any unrecognised property inside a rewrite object rather than ignoring
it (`rewrites[0] should NOT have additional property 'comment'`). So the
reasoning lives here. Don't add comment keys back to that file.

Check after deploying:

```bash
curl -sI https://<site>/.well-known/apple-app-site-association
# expect: 200, content-type: application/json, and no 3xx
curl -s  https://<site>/.well-known/apple-app-site-association
# expect: the real TEAMID.com.yourco.reelmap — not the 503 error body
```

Then on a device: create an invite in the app, send yourself the link, tap it.
It must open the app, not Safari. **Delete and reinstall first** — iOS caches
that file per install and won't re-fetch it.

## The domain

`noshmap.app` — the apex is canonical, `www` redirects to it. Four places have
to agree, and all four are set:

1. `astro.config.mjs` → `site`
2. `public/robots.txt` → the `Sitemap:` line
3. Railway, **both** services → `PUBLIC_BASE_URL` (this builds the invite URL)
4. `ios/project.yml` → `APP_LINK_DOMAIN`

The app's entitlement lists both `noshmap.app` and `www.noshmap.app`, so a link
either way opens the app rather than bouncing to Safari.

If the domain ever changes again: after step 4 everyone must delete and
reinstall, because iOS caches `apple-app-site-association` per install and will
not re-fetch it.

## Screenshots

Placeholders render at true iPhone aspect ratio, so dropping images in shifts
nothing. Put files in `public/shots/` and pass `src` to `<Shot />`.

**These are the same assets App Store submission needs — shoot once, use twice.**
Capture at 1290 × 2796 (iPhone 15/16 Pro Max).

| # | Where | What to capture |
|---|---|---|
| 1 | Hero | Map screen, pins visible, filter chips along the top. Your best-looking screen — this is the first thing anyone sees |
| 2 | How it works, step 1 | Instagram's share sheet with Nosh visible in the app row |
| 3 | How it works, step 2 | The analyzing state — progress card with the reel thumbnail |
| 4 | How it works, step 3 | Map with ~10 pins and the filter chips |
| 5 | Features | A city list showing many places extracted from one reel |
| 6 | Features | Place detail — tips, what to order, hours |
| 7 | Features | The map with a cuisine filter applied |
| 8 | Shared maps | A shared map showing member avatars, or the invite sheet |

Logo assets are real now. `public/wordmark.svg` is the horizontal mark, inlined
by `src/components/Wordmark.astro` so it inherits `currentColor` and works in
both themes. `favicon.png` and `apple-touch-icon.png` are downscaled from the
app icon at `ios/ReelMap/Assets.xcassets/AppIcon.appiconset/icon-1024.png`, so
the browser tab and the phone home screen show the same mark — regenerate both
if that icon changes.

## Copy that is load-bearing

Two paragraphs are not decorative and should not be edited casually:

- **`src/pages/terms.astro`, section 4** — the neutral-tool clause ("Nosh acts
  solely as a tool to organise and bookmark content available publicly or via
  your personal accounts"). This is the app's position on third-party content.
- **`src/pages/terms.astro`, section 12** — the Apple Inc. notice. Apple
  requires these clauses when not using their standard EULA.

Terms §3 and the support page describe the in-app Report and Block features
(`ios/ReelMap/ReportSheet.swift`, and the menus in `MapDetailSheet`,
`PlaceDetailScreen` and `ProfileSheet`). If that UI moves, update both pages —
a legal document describing a feature that isn't there is worse than one that
says nothing.
