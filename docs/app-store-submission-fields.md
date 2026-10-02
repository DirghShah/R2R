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

## A11. Build — ⚠️ this one is wrong

The page shows **Build 13** attached. You tested and signed off **build 15**.

Click the build row and select 15. If 15 isn't offered, it either hasn't
finished processing or it got an email about a missing compliance answer —
check the TestFlight tab.

Shipping 13 would mean every fix that went into 14 and 15 — the delete-pin
crash, the map-settings crash, the invites crash, the share toast, the vibe
search UI — is absent from the version the public gets, while your screenshots
show it. Worth double-checking before anything else on this page.

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

## B2. Age Rating (same App Information page)

Answer **None** to every frequency question. The two that aren't obvious:

- **Unrestricted Web Access → No.** Reel links open in Safari or the host app;
  there's no in-app browser.
- **User-Generated Content → Yes**, and then Infrequent/Mild. Shared maps let
  invited people add places. Say yes: you have reporting and blocking built,
  this is exactly what they're for, and answering no while shipping a sharing
  feature is the kind of mismatch that gets caught on a later update.

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

## B5. EU Trader Status

Required for anything distributed in the EU, and the only item here I won't
answer for you. Submitting as an individual rather than a registered business
points one way, but it's a legal declaration with real consequences — read
Apple's own text on that screen before you answer. If you'd rather not deal
with it today, the alternative is to deselect EU countries in B4 and submit
everywhere else.

---

# C. Already done ✅

- Encryption / export compliance — standard encryption, declared
- France distribution — answered no
- Build uploaded and processed
- App icon present ("Included Assets" shows it)
- Screenshots uploaded

---

# D. Order of operations

1. **Switch the build to 15** (A11) — nothing else matters if this is wrong
2. Set `EXAMPLE_REEL_URL` on Railway, curl it, confirm 200 (A14)
3. Open `noshmap.app/support` and `/privacy` in a browser (A5, B1)
4. Reorder the three screenshots (A1)
5. Paste A2 → A8, A14; set release to Manual (A16)
6. App Information + Age Rating (B1, B2)
7. App Privacy (B3) — the sleeper
8. Pricing (B4), EU trader status (B5)
9. **Add for Review**
