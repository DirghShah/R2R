#!/bin/sh
# Run migrations, then start whatever command was passed.
#
# The API and worker share this image and both boot at once, so they can race
# on the very first deploy. Alembic locks alembic_version, so the loser just
# errors — retrying a couple of times lets it resolve itself instead of failing
# the deploy.
set -e

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
