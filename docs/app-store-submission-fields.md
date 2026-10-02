# Filling in the submission — field by field

The page you printed is the **version page** (`1.0 — Prepare for Submission`).
It is not all of it: four things that block submission live on *other* pages in
the left sidebar, and they're in section B.

Everything below is copy-paste ready.

---

# A. The version page (the one in your PDF)

## A1. Previews and Screenshots — done ✅

"8 of 10 Screenshots", 6.5" showing *Using 6.9" Display*. That's correct and
finished.

One thing left: **drag them into order.** Apple's own note on that page says
*"only the first 3 will be used on the app installation sheets."* Your current
first three are place search, Uchiko detail, shared map. Make them:

1. Uchiko place detail (the strongest single image)
2. Vibe search
3. Map with all pins

0 of 3 App Previews is fine — video previews are optional, and shooting one
badly is worse than having none.

## A2. Promotional Text — 170 limit

```
Share a food reel and Nosh pins every place it mentions — address, hours, what to order. Then search your map by vibe: "somewhere quiet I can work."
```

148 chars. This field is editable later **without submitting a new build**, so
it's where launch news goes once you're live.

## A3. Description — 4,000 limit

Paste the block from `docs/app-store-listing.md` § 5 (1,965 chars). It's the
long one opening *"You have two hundred saved reels. You've been to none of
them."*

## A4. Keywords — 100 limit

```
restaurant,where to eat,saved,bookmark,foodie,dining,cafe,eats,places,travel,bucket list,pins,video
```

99 chars. No spaces after the commas — spaces count against the 100.

## A5. Support URL

```
https://noshmap.app/support
```

**Check this loads in a browser before you submit.** Apple actually opens the
Support URL during review, and a 404 here is a boring, certain rejection. I
can't verify it from this environment — the proxy blocks the domain — but the
page exists in the repo (`web/src/pages/support.astro`), so this is really a
question of whether the Vercel deploy and the custom domain are both live.

## A6. Marketing URL — optional

```
https://noshmap.app
```

## A7. Version — done ✅

`1.0` is already correct.

## A8. Copyright — 200 limit

```
2026 Dirgh Shah
```

Apple wants the year of first publication plus the **person or legal entity**
that owns the rights. Use `2026 Nosh` only if Nosh is a registered business;
if you're shipping as an individual, your own name is the accurate answer.

## A9. Routing App Coverage File — skip

That's for turn-by-turn navigation apps that take over routing requests. Nosh
shows a map; it doesn't route. Leave it empty.

## A10. App Clip / iMessage App — skip

Not applicable, and the page already tells you so.

## A11. Build — "13" may well be the right binary

I previously said build 13 meant the crash fixes were missing. That was an
inference stated far too confidently, and it is probably wrong. Here is the
actual picture.

`ios/project.yml` says `CURRENT_PROJECT_VERSION: "15"`, and the build numbers
map to commits like this:

| Build | Commit | What it added |
|---|---|---|
| 13 | `58cd3c5` | Teach vibe search at the moment somebody needs it |
| 14 | `55850b7` | **Fix the delete crash, the stacked sheets, the suggestion takeover** |
| 15 | `f761973` | Second attempt at the share toast backdrop |

The number that reaches App Store Connect comes from the **`.xcodeproj`**, not
from `project.yml`. XcodeGen only writes that number when you re-run
`xcodegen generate`. So if you pulled the new source and archived *without*
regenerating, Xcode compiled the new code and stamped it with the old number.

And that works cleanly here, which is the key point: **builds 14 and 15 added no
new files.** Every change is an edit to `CityListsScreen.swift`,
`MapScreen.swift`, `MapSwitcherSheet.swift` and `ShareViewController.swift` —
all four already in the project. A stale project file would still compile all
of the new code. Nothing would be silently left out.

So "it is listed as 13 but it is the build I tested" is a completely coherent
account, and most likely what happened.

### Settling it in sixty seconds

Don't take my word for it either way — the binary itself will tell you. Install
build 13 from TestFlight on your phone and do four things:

1. Delete a pin
2. Open map settings
3. Open invites
4. Share a reel from Instagram and watch the toast

If 1–3 don't crash, build 14's fixes are in that binary and you are safe to
submit. Those three crashes are the only rejection-grade problem in play; a
reviewer deleting a pin and watching the app quit is Guideline 2.1.

If 4 shows the toast on a black background, build 15's fix didn't make it. That
is cosmetic — ship it and fix it in 1.0.1 rather than burning a build cycle.

Also worth a glance: the build's **upload date** in TestFlight. Today's date
means it's the recent archive.

### If you want certainty instead

Bump `CURRENT_PROJECT_VERSION` to `16`, run `xcodegen generate`, archive and
upload. 16 because App Store Connect refuses a version+build pair it has
already seen, and 13 is now taken. That costs a build cycle and is only worth
it if the test above actually crashes.

## A12. App Review Information → Sign-In Information

**Leave "Sign-in required" unchecked.**

That sounds wrong, so here's the reasoning. The checkbox exists so you can hand
Apple a username and password. Nosh has neither — Sign in with Apple is the
only method, there's no password anywhere in the system, and the reviewer signs
in with their own Apple ID (which works on both the Simulator and a device).
Ticking the box makes the two credential fields required and you'd have to
invent something that doesn't work.

What stops the "we couldn't get in" rejection is the Notes field, which is why
A14 leads with it.

And to be explicit: the `ALLOW_DEV_SIGN_IN` shortcut is **not** an option here.
It's a complete auth bypass and must never be enabled on the deployed service,
reviewer or no reviewer.

## A13. App Review Information → Contact Information — leave as-is ✅

`Dirgh Shah / 2179042903 / dirghvshah@gmail.com`

Your personal email is the *right* answer here. This block is private — it's
how Apple reaches you mid-review, and it never appears on the product page. The
business address belongs on the public side (Support URL, the support page's
contact line), which is already `noshmap@outlook.com`.

Being reachable fast matters more than consistency: if a reviewer asks a
question and nobody answers, the submission sits in "Waiting for Review" for
days.

## A14. App Review Information → Notes — 4,000 limit

Paste the block from `docs/app-store-listing.md` § 8. It opens with WHAT THE
APP DOES and covers sign-in, the one-tap example, the full test flow, video
storage, account deletion, UGC moderation and push.

⚠️ **Before you paste it, do the Railway step in § 9 of that file**
(`EXAMPLE_REEL_URL`). The notes tell the reviewer to tap *"Try it with an
example"*, and that button returns a 404 error toast unless the variable names
a reel already analysed in production. A reviewer tapping it and seeing
*"Couldn't load that just now"* on an empty map is the worst possible first
thirty seconds. Either set the variable or delete that paragraph.

## A15. Attachment — skip

Optional, and for things like a licence or a demo video. Nothing to add.

## A16. App Store Version Release

Pick **"Manually release this version."**

Approval arrives whenever it arrives, often overnight. Manual release means you
decide the moment it goes public — which matters because two things have to
happen *at* launch, not after it:

- `appStoreURL` in `web/src/pages/index.astro` is still `null`, so both site
  CTAs read "Coming soon on iPhone" until you set it and redeploy
- `APP_STORE_URL` on Railway

Automatic release puts the app live while the site still says it isn't out.

---

# B. Not on your page, but still blocks submission

Check each of these in the left sidebar. The submit button won't go green until
all four are done, and App Privacy is the one people forget.

## B1. App Information (sidebar → General → App Information)

| Field | Value |
|---|---|
| Name | `Nosh: Food Reels to Map` |
| Subtitle | `Every food reel, on one map` |
| Privacy Policy URL | `https://noshmap.app/privacy` |
| Primary Category | **Food & Drink** |
| Secondary Category | **Travel** |
| Content Rights | "No, it does not contain, show, or access third-party content" |

On Content Rights: Nosh stores *its own* derived text plus a URL, and fetches
frames transiently from a link the user supplies. It doesn't host, display or
redistribute anyone's video. If you'd rather answer yes, you then have to
assert you have the necessary rights — which you don't, and don't need, because
you aren't using the content.

## B2. Age Rating — where to find it

**Apps → Nosh → sidebar, under General → App Information → below Age Ratings,
click "Set Up Age Ratings".**

Apple replaced this questionnaire recently, so it is longer than the old one and
now asks about in-app controls and capabilities as well as content. Answer
**None** to every content-frequency question. The ones that need a real answer:

- **Unrestricted Web Access → No.** Reel links open in Safari or the host app;
  there is no in-app browser.
- **User-generated content → Yes**, then the lowest frequency offered. Shared
  maps let invited people add places. Say yes: you built reporting and
  blocking, this is what they are for, and claiming no while shipping a sharing
  feature is the kind of mismatch that surfaces on a later update.
- **Messaging / unmoderated chat → No.** There is no chat.
- **Medical/wellness, violence, gambling, loot boxes → None.**

Expected result: **4+**.

## B3. App Privacy (sidebar → App Privacy) — the one that gets forgotten

This is a separate questionnaire from Age Rating and it is mandatory. Based on
what the code actually does:

**Do you collect data? → Yes.** Then declare exactly these five:

| Category | Linked to user? | Tracking? | Purpose |
|---|---|---|---|
| **Coarse Location** | Yes | No | App Functionality |
| **Name** | Yes | No | App Functionality |
| **User ID** | Yes | No | App Functionality |
| **Device ID** | Yes | No | App Functionality |
| **Other User Content** | Yes | No | App Functionality |

Why each — so you can answer follow-ups confidently:

- **Coarse Location** — this one is easy to get wrong in the other direction.
  Location is mostly on-device (centring the map, distance labels), but
  `PlaceSearchScreen` does send your coordinates to `GET /places/suggest` to
  bias restaurant autocomplete toward where you are. That leaves the device, so
  it must be declared. It's `kCLLocationAccuracyHundredMeters` and isn't
  stored, which is why it's *Coarse*, not *Precise*.
- **Name** — `users.display_name`. Apple hands over `fullName` once on first
  authorization and never again, so it's kept.
- **User ID** — `users.apple_sub`, the Apple subject identifier.
- **Device ID** — the APNs token in `devices.apns_token`, for "your reel is
  ready" notifications.
- **Other User Content** — the places, tips and reel URLs the user saves.

**Not collected, and worth knowing:** no email address anywhere. Sign in with
Apple gives you `apple_sub` and nothing else, and there's no email column in
the schema. Don't declare Email Address — over-declaring is a privacy label
that's wrong in the other direction.

**Tracking → No, for everything.** `ios/project.yml` declares zero third-party
packages. No analytics SDK, no ad network, no attribution kit, nothing that
follows anyone anywhere. That also means **no App Tracking Transparency prompt
is needed**, so don't add one.

## B4. Pricing and Availability (sidebar)

- Price: **Free**
- Availability: all countries, unless you want to start smaller
- Pre-orders: no

## B5. EU Trader Status — where to find it

Two places, because it is set per account and can then be overridden per app.

**Account level:** **Business** (top nav) → **Agreements** tab → scroll to
**Compliance** → next to Digital Services Act, click **Complete Compliance
Requirements**. Needs the Account Holder or Admin role, which you have.

**Per app:** Apps → Nosh → **App Information** → scroll to **App Store
Regulations and Permits** → under Digital Services Act, click **Edit**.

If you skip it, App Store Connect asks you at submission time anyway, so it is
not escapable — but it is also not a blocker you need to solve before starting
the other fields.

### The actual decision

Under the DSA a trader is someone acting for purposes relating to their trade
or business. In practice Apple's threshold is **whether the app makes money
through the App Store** — paid downloads, in-app purchases, or even ads. Nosh
is free, has no IAP and carries no advertising, so "this is not a trader
account" is a defensible declaration.

Two things to weigh, and then it is your call:

- **Declaring trader as an individual publishes your home address and phone
  number on the Nosh product page.** That is not a side effect, it is the point
  of the requirement. For an indie developer working from home it is a real
  cost, and a P.O. Box is the usual way around it.
- **Declaring "not a trader" is not the same as leaving it blank.** The ~135,000
  apps Apple pulled from EU storefronts in February 2025 were ones with *no
  status provided at all*. A declared non-trader status is a complete answer.

What I could not confirm from Apple's own documentation is whether a verified
non-trader app is still distributed in the EU or quietly excluded from those
storefronts — the help page doesn't say, and I'm not going to guess at
something that decides whether you have a European market. The screen itself
states the consequence when you pick. Read what it says before confirming, and
if it tells you EU availability is affected, that is the authority, not me.

---

# C. Already done ✅

- Encryption / export compliance — standard encryption, declared
- France distribution — answered no
- Build uploaded and processed
- App icon present ("Included Assets" shows it)
- Screenshots uploaded

---

# D. Order of operations

1. **Install build 13 from TestFlight and try delete-pin, map settings, invites**
   (A11). This is the only thing that could get you rejected. If it passes, the
   build is fine as listed.
2. Set `EXAMPLE_REEL_URL` on Railway and curl it for a 200 — your Notes field
   already tells the reviewer to tap that button (A14)
3. Open `noshmap.app/support` and `/privacy` in a browser (A5, B1)
4. Confirm the first three screenshots are Uchiko detail, vibe search, map (A1)
5. Confirm **"Manually release this version"** is the selected radio (A16)
6. App Information: Name, Subtitle, Categories, Privacy Policy URL, Content
   Rights (B1)
7. Age Rating questionnaire (B2)
8. **App Privacy** (B3) — the one that gets forgotten
9. Pricing and Availability (B4)
10. EU trader status (B5)
11. **Add for Review**
