#!/bin/sh
# Run migrations, then start whatever command was passed.
set -e

# The single most common deploy failure: the service was never given a
# reference to the managed database, so it silently falls back to the localhost
# default and every migration attempt fails with a connection error.
case "${DATABASE_URL:-}" in
  ""|*localhost*|*127.0.0.1*)
    echo "[entrypoint] FATAL: DATABASE_URL is unset or points at localhost." >&2
    echo "[entrypoint] On Railway, add a variable to THIS service:" >&2
    echo "[entrypoint]     DATABASE_URL=\${{Postgres.DATABASE_URL}}" >&2
    echo "[entrypoint] Adding a Postgres plugin does not expose it to other services." >&2
    exit 1
    ;;
esac

case "${REDIS_URL:-}" in
  ""|*localhost*|*127.0.0.1*)
    echo "[entrypoint] WARNING: REDIS_URL is unset or localhost." >&2
    echo "[entrypoint] Add: REDIS_URL=\${{Redis.REDIS_URL}} — reel analysis will not run without it." >&2
    ;;
esac

# The API and worker share this image and both boot at once, so they can race
# on the very first deploy. Alembic locks alembic_version, so the loser just
# errors — retrying a couple of times lets it resolve itself.
n=0
until alembic upgrade head; do
  n=$((n + 1))
  if [ "$n" -ge 3 ]; then
    echo "[entrypoint] migrations failed after $n attempts" >&2
    exit 1
  fi
  echo "[entrypoint] migration attempt $n failed (likely racing the other service), retrying..."
  sleep 3
done

echo "[entrypoint] migrations applied, starting: $*"
exec "$@"
