# Shipping an update

Written for 1.0.1 and reusable for every release after it. The last section is
the only part you change next time.

---

## 0. Pre-flight — nothing to flip

Everything that used to be a manual step before archiving is already committed
and correct:

| Setting | Value | Where |
|---|---|---|
| `aps-environment` | `production` | `ios/project.yml:88` |
| `API_BASE_URL` | `https://r2r-production-727a.up.railway.app` | `ios/project.yml:29` |
| `MARKETING_VERSION` | `1.0.1` | `ios/project.yml:25` |
| `CURRENT_PROJECT_VERSION` | `16` | `ios/project.yml:26` |
| `DEVELOPMENT_TEAM` | `98B96Q5HQP` | `ios/project.yml:17` |
| Scheme | declared in `project.yml` | so XcodeGen can't lose it |

Do **not** hand-edit these in Xcode. `project.yml` is the source of truth and
`xcodegen generate` overwrites the project every time.

The backend needs nothing: Railway auto-deploys this branch, so every backend
fix is already live.

---

## 1. On the Mac

```bash
cd ~/Repos/R2R
git pull
cd ios
xcodegen generate
```

**Re-running XcodeGen is not optional.** It is what writes 1.0.1 and build 16
into the project file. Skipping it is how a build once went up stamped 13 when
the source said 15 — Xcode compiles the new code but keeps the old numbers, and
nothing warns you.

Then open the project:

```bash
open Nosh.xcodeproj
```

---

## 2. Archive

1. Scheme selector (top left): **Nosh**
2. Destination: **Any iOS Device (arm64)** — Archive is greyed out on a simulator
3. **Product → Archive**
4. Wait for the Organizer window

If the build fails, it is almost always a type error in a file changed since the
last build — `check.py` catches syntax and missing imports but cannot type-check.
Send the error rather than guessing at it.

---

## 3. Upload

In the Organizer:

1. Select the new archive → **Distribute App**
2. **App Store Connect** → **Upload**
3. Accept the defaults (automatic signing, symbols included)
4. **Upload**, then wait for the "processing complete" email — usually 5-15
   minutes

---

## 4. App Store Connect

**Create the version.** App Store tab → **+ Version or Platform** → iOS →
`1.0.1`.

**What's New in This Version** — required for updates, unlike a first release:

> Fixes a crash when removing a saved place, and shared maps now appear as soon
> as you join them instead of after restarting the app.

**Build** — select **16**. If it isn't listed yet, processing hasn't finished.

**Everything else carries over.** Screenshots, description, keywords, age
rating, privacy, category: untouched unless you want to change them.

**Release option** — *Manually release this version*. Approval then parks at
"Pending Developer Release" until you press the button, which is what you want
whenever a release needs anything done alongside it.

**Add for Review.**

---

## 5. After approval

Updates are usually reviewed inside 24 hours — far faster than a first
submission, which is what took three weeks.

When it clears, press **Release**. Nothing else needs doing for this one; the
website and `APP_STORE_URL` were set at 1.0 launch and do not change per
release.

---

## 6. Next time

Two lines in `ios/project.yml`, before you archive:

- `MARKETING_VERSION` → the new user-facing version (`1.0.2`, `1.1`)
- `CURRENT_PROJECT_VERSION` → **always** increase it

App Store Connect refuses a version+build pair it has already seen, and a
rejected upload after a ten-minute archive is a bad way to find that out. Bump
the build number for *every* upload, even a re-upload of the same version.
