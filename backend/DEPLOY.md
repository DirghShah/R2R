# Deploying the ReelMap backend

Two services off one image (`api` + `worker`), plus managed Postgres and Redis
— exactly what `docker-compose.yml` already describes locally.

Recommended host: **Railway**. It reads the `Dockerfile`, Postgres and Redis are
one-click, and you get an HTTPS domain immediately. Everything below works the
same on Fly.io with different plumbing.

---

## 1. Create the project

1. <https://railway.app> → sign in with GitHub.
2. **New Project → Deploy from GitHub repo** → pick `DirghShah/R2R`.
3. Once the service appears: **Settings → Root Directory → `backend`**.
   **This is the #1 cause of a failed build.** The repo root holds `backend/`,
   `ios/` and `docs/` with no Dockerfile, so without this Railway cannot work
   out what to build and fails during "Build image".
4. **Settings → Branch** → `claude/bold-maxwell-2d4wya` (or merge to `main`
   first and deploy that).

## 2. Add the databases

In the project canvas: **+ New → Database → Add PostgreSQL**, then again for
**Redis**.

**Adding them does NOT make them visible to your app service.** The connection
strings live on the database services; your app has to reference them. On the
api service → **Variables**, add:

```
DATABASE_URL=${{Postgres.DATABASE_URL}}
REDIS_URL=${{Redis.REDIS_URL}}
```

(Use whatever Railway named the services — check the canvas; usually `Postgres`
and `Redis`.) Without this the app falls back to the localhost default, the
migration can't connect, and the deploy dies at **Healthcheck**. The entrypoint
now detects this and says so in the deploy log rather than failing silently.

> Plain Postgres is correct. The PostGIS image in `docker-compose.yml` is
> aspirational — the code stores lat/lng as floats.

## 3. Set the environment variables

**Variables** tab on the api service, on top of the two references from step 2.

```
ENVIRONMENT=prod
JWT_SECRET=<paste a long random string>
PUBLIC_BASE_URL=https://<your-railway-domain>

ANTHROPIC_API_KEY=sk-ant-...
ANTHROPIC_MODEL=claude-haiku-4-5

REEL_FETCHER=apify
APIFY_TOKEN=...

GEOCODER=google
GOOGLE_PLACES_API_KEY=...

APNS_KEY_CONTENT=<base64 of your AuthKey_XXXX.p8>
APNS_KEY_ID=<from the Apple key page>
APNS_TEAM_ID=98B96Q5HQP
APNS_TOPIC=com.yourco.reelmap
APNS_USE_SANDBOX=true

FREE_MONTHLY_REEL_LIMIT=50
RATE_LIMIT_REELS_PER_HOUR=20
```

Generate the secret and the APNs blob locally:

```bash
python3 -c "import secrets; print(secrets.token_urlsafe(48))"   # JWT_SECRET
base64 -i ~/Downloads/AuthKey_XXXXXXXXXX.p8 | tr -d '\n'         # APNS_KEY_CONTENT
```

`APNS_KEY_PATH` has no meaning here — a managed platform gives you env vars,
not files. That's what `APNS_KEY_CONTENT` is for.

**`ENVIRONMENT=prod` matters:** it makes the backend reject `dev:` auth tokens.
The iOS app still sends `dev:me`, so it will *not* be able to sign in until
real Sign in with Apple ships. That's expected at this stage — verify the API
with curl (step 6) first.

## 4. Add the worker service

**+ New → GitHub Repo → same repo.** Then on that service:

- **Settings → Root Directory** → `backend`
- **Settings → Custom Start Command** → `python -m worker.run`

  Not `rq worker --url $REDIS_URL reels` — Railway hands the start command to
  the container as an argument vector, so `$REDIS_URL` arrives as that literal
  string and the worker crashes trying to resolve it as a hostname.
- **Settings → Deploy → Healthcheck Path** → leave **empty**. A worker serves no
  HTTP, so a healthcheck can never pass and Railway would mark every deploy
  failed even though the worker is running fine. This is why `railway.json`
  deliberately does *not* set one — both services share that file.
- **Variables** → the same list as the api, **including** the
  `${{Postgres.DATABASE_URL}}` and `${{Redis.REDIS_URL}}` references. Each
  service needs its own copy; they are not shared across services.

Both services run `alembic upgrade head` on boot via `entrypoint.sh`. They can
race on the very first deploy; the entrypoint retries, so it resolves itself.

## 5. Get the domain

**On the api service only** — the worker never receives HTTP traffic and should
stay unexposed.

api service → **Settings → Networking → Generate Domain**. Optionally set
**Healthcheck Path** to `/health` here (api only). Copy the domain into
`PUBLIC_BASE_URL` on **both** services and redeploy — invite links are built
from it.

## 6. Verify

```bash
API=https://<your-domain>

curl -s $API/health
# {"status":"ok","env":"prod"}

curl -s $API/docs -o /dev/null -w '%{http_code}\n'   # 200

# Universal Links file — must be JSON, no redirect
curl -si $API/.well-known/apple-app-site-association | head -5

# dev: tokens must be REJECTED now
curl -s -X POST $API/auth/apple \
  -H 'content-type: application/json' \
  -d '{"identity_token":"dev:me"}'
# {"detail":"Invalid Apple identity token: ..."}   <- correct
```

Check the worker log for `[entrypoint] migrations applied` and an RQ banner.

### Prove the pipeline end to end

`ENVIRONMENT=prod` rejects `dev:` sign-in, which is correct — do **not** flip it
back to `dev` to test. Mint a token from inside the container instead:
Railway → api service → **Console** tab →

```bash
python scripts/dev_token.py
```

Copy the access token, then from your Mac:

```bash
API=https://<your-domain>
AUTH="Authorization: Bearer <paste the token>"

curl -s $API/me   -H "$AUTH"    # profile + avatar colour
curl -s $API/maps -H "$AUTH"    # personal map, auto-created on first call

# A real reel. This costs money (~$0.27 for 5 places) — use one you know.
curl -s -X POST $API/reels -H "$AUTH" -H 'content-type: application/json' \
  -d '{"url":"https://www.instagram.com/reel/XXXXXXXXX/"}'

sleep 60
curl -s $API/reels  -H "$AUTH"   # status should be "done"
curl -s $API/places -H "$AUTH"   # pins, each tagged with map_id
```

Watch the **worker** Deploy Logs while that runs — you'll see the pipeline
stages and then the `[metrics]` cost line.

Then sharing:

```bash
MAP=$(curl -s -X POST $API/maps -H "$AUTH" -H 'content-type: application/json' \
  -d '{"name":"Dallas Eats","emoji":"🌮"}' | python3 -c 'import sys,json;print(json.load(sys.stdin)["id"])')

curl -s -X POST $API/maps/$MAP/invite -H "$AUTH"    # invite_url
```

Open that `invite_url` in a browser — you should get the fallback landing page
with the map name on it. That is what someone without the app sees.

Clean up the smoke-test account when you're done:

```bash
curl -s -X DELETE $API/me -H "$AUTH"    # removes the user and its maps/places
```

## 7. Watch the cost log

Worker logs print a `[metrics]` line per reel with the real cost:

```
[metrics] {'reel': '...', 'places': 5, 'total_cost_usd': 0.2712, ...}
```

Google Places is ~90% of it at $0.05/place. If that line looks wrong, fix it
before inviting anyone — it is the number that scales with usage, not hosting.

---

## Known limitations at this stage

- **The iOS app cannot sign in against `ENVIRONMENT=prod`** until real Sign in
  with Apple ships. That's the next chunk of work.
- **Apple token revocation on account deletion is a no-op** until
  `APPLE_TEAM_ID` / `APPLE_KEY_ID` / `APPLE_PRIVATE_KEY` are set (a *Sign in
  with Apple* key, separate from the APNs one). Only needed before App Store
  submission.
- **yt-dlp frame sampling may degrade from a datacenter IP.** Instagram treats
  cloud IPs far more harshly than residential ones. Apify (the primary fetcher)
  is an API and is unaffected — but if extraction quality drops on music-only
  reels, this is why. Measure it rather than assuming.
