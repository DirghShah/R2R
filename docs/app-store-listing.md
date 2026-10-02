# App Store Connect — listing copy

Everything here is ready to paste. Character counts are given where Apple
enforces a limit; all of them are inside it.

---

## 1. App Name — 30 char limit

**Nosh: Food Reels to Map**  — 23 chars

The name field is indexed for search, so it is worth more than just "Nosh".
If you have already set the name to something else and don't want to change it,
that's fine — nothing else here depends on it.

Alternatives, if you prefer:
- `Nosh — Save Food Reels` (22)
- `Nosh: Restaurant Map` (20)

---

## 2. Subtitle — 30 char limit

**Every food reel, on one map**  — 27 chars

Alternatives:
- `Turn saved reels into pins` (26)
- `Your saved reels, mapped` (24)

---

## 3. Promotional text — 170 char limit

Editable any time *without* submitting a new build, so use it for launch news
later. For now:

> Share a food reel and Nosh pins every place it mentions — address, hours,
> what to order. Then search your map by vibe: "somewhere quiet I can work."

— 148 chars

---

## 4. Keywords — 100 char limit, comma-separated, no spaces after commas

```
restaurant,where to eat,saved,bookmark,foodie,dining,cafe,eats,places,travel,bucket list,pins,video
```

— 99 chars

Two things to know about this field:

- **Apple already indexes your app name and subtitle**, and combines words
  across all three. So "food", "reel" and "map" are deliberately *not* here —
  they're in the subtitle, and repeating them wastes the budget.
- **No competitor or brand names.** "instagram", "tiktok" and "youtube" are
  other companies' trademarks and are a common rejection reason in this field.
  They're fine in the description, which is where I've used them.

---

## 5. Description — 4000 char limit

Paste exactly as-is (it's 1,965 chars). The description is *not* indexed for
search, so it's written for a person deciding whether to tap Get.

```
You have two hundred saved reels. You've been to none of them.

Nosh turns them into a map.

Share a food reel from Instagram, TikTok or YouTube — or paste a link a friend sent you — and about thirty seconds later every restaurant and cafe it mentioned is a pin on your map, with the address, the hours, what to order, and a link back to the reel you got it from.


EVERY PLACE, NOT JUST THE FIRST ONE

A "9 cafes in Dallas" reel becomes nine pins. Most places live in the text burned onto the screen or in what the creator says out loud, not in the caption — so Nosh reads all of it: the caption, the frames, the audio, the tagged accounts.


IT REMEMBERS WHAT TO ORDER

The dish the creator raved about. The tip about going before noon. The note that they only take cash. Pulled out of the reel and kept with the pin, so it's there when you finally walk in.


SEARCH BY VIBE, NOT BY NAME

You don't remember what the place was called. You remember the feeling. So ask for it:

"somewhere quiet I can actually work"
"impressive but not stuffy, for a second date"
"cheap late-night food near the water"

Nosh searches what the reels actually said about your saved places — and tells you why each result matched.


FINDABLE WHEN YOU'RE ACTUALLY HUNGRY

Filter by cuisine. Browse by city. Or just open the map and see what's near you right now. Saved folders are a graveyard; a map is a plan.


MAPS YOU CAN SHARE

Send a map to friends by link. Everyone who joins can add their own reels to it, and you can see who added what. Good for a trip, a city, or a running list of places you keep meaning to try.


NO REEL? NO PROBLEM

Search for any restaurant by name and add it straight to your map, with or without a video.


WE DON'T STORE THE VIDEOS

Frames and audio are fetched, read, and thrown away. What's kept is the place data and a link back to the original reel.


Nosh is free. Fair-use cap of 50 reels a month, which is more than almost anyone gets through.
```

---

## 6. Category

| Field | Value |
|---|---|
| Primary | **Food & Drink** |
| Secondary | **Travel** |

Food & Drink is a much less crowded top-chart than Travel, which matters
more at launch than category fit does.

---

## 7. Supporting fields (already settled)

| Field | Value |
|---|---|
| Support URL | `https://noshmap.app/support` |
| Marketing URL | `https://noshmap.app` |
| Privacy Policy URL | `https://noshmap.app/privacy` |
| Copyright | `2026 Nosh` |
| Support email | `noshmap@outlook.com` |

---

## 8. App Review notes

Paste into **App Review Information → Notes**. Reviewers reject food apps for
sign-in walls and for "where's the content?" more than for anything else, so
this pre-empts both.

```
WHAT THE APP DOES
The user shares (or pastes) a link to a short food video they already follow. Nosh reads the public caption, on-screen text and audio of that link, extracts the restaurants mentioned, geocodes them, and drops map pins with tips and hours. Users bring their own links; Nosh does not browse, host, recommend or index any third-party catalog of videos.

SIGN IN
Sign in with Apple is the only sign-in method. No account creation form, no email/password, no other credentials needed. Please use the Simulator or a device Apple ID.

HOW TO SEE IT WORK IN ONE TAP
A brand-new account has an empty map, which is expected. The welcome screen that appears on first launch has a "Try it with an example" button. It puts a few real places on the map in about a second, so you can see pins, place detail and search without waiting for any processing. They are ordinary places and can be deleted.

TO TEST THE FULL FLOW
1. Open Instagram, TikTok or YouTube, find any restaurant video, tap Share, pick Nosh. (Or copy the link, open Nosh, use the Add tab and paste it.)
2. Processing takes roughly 30 seconds. You can close the app; a notification arrives when it finishes.
3. Pins appear on the Map tab and grouped by city on the Lists tab.
4. Tap a pin for the address, hours, what to order, and a link back to the original video.
5. On the Lists tab, try the search bar with a phrase like "somewhere quiet I can work" to see vibe search.

VIDEO STORAGE
No video is stored. Frames and audio are fetched transiently, analyzed, and discarded. Only the derived place text and the original URL are retained.

ACCOUNT DELETION
Profile tab → Delete account. It permanently removes the account and all saved places, in-app, with no email required.

USER-GENERATED CONTENT
Shared maps let invited users add places. Reporting and blocking are both available from the place detail and member rows, and blocked users' contributions are hidden.

PUSH NOTIFICATIONS
Used only to tell the user their own reel finished processing.
```

---

## 9. One thing to do on Railway first

The review notes above point the reviewer at **"Try it with an example"** on the
welcome screen. That button calls `POST /reels/example`, which returns 404
unless `EXAMPLE_REEL_URL` is set to a reel that is already `status=done` in
production — and the app doesn't pre-check, so a reviewer who taps it would see
*"Couldn't load that just now."* That reads as a broken app.

So either set it, or delete the "HOW TO SEE IT WORK IN ONE TAP" paragraph from
the notes. Setting it is better: a reviewer with an empty map and no Instagram
account is a rejection risk.

To pick one, run this against production and take the top-scored reel:

```
cd backend && python3 scripts/nosh_stats.py --example
```

Then on Railway, add `EXAMPLE_REEL_URL=<that reel's URL>` to **both** the API
and the worker service, and verify:

```
curl -s -X POST https://r2r-production-727a.up.railway.app/reels/example \
  -H "Authorization: Bearer $TOKEN"
```

A `200` with `"already_analyzed": true` means the reviewer's first tap will
work. No rebuild needed — it's server-side config only.

---

## 10. Still to answer in the console (not copy)

- **Age rating questionnaire** — everything is "None" except *Unrestricted
  Web Access*: answer **No** (links open in Safari/the host app, there is no
  in-app browser). Expected result: **4+**.
- **EU trader status** — the one item with no safe default. If you're
  submitting as an individual rather than a registered business, you'll likely
  select "I am not a trader," but that declaration has legal consequences in
  the EU and is yours to make, not mine. Apple's own guidance for that field is
  the thing to read before answering.
- **Screenshot order** — drag so the first three are Uchiko place detail, vibe
  search, then the map with all pins. Only the first three show on the install
  sheet.
