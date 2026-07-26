#!/bin/sh
# Run migrations, then start whatever command was passed.
#
# The API and worker share this image; only one of them should migrate, but
# Alembic takes a lock on alembic_version so a concurrent second run is a no-op
# rather than a corruption.
set -e
echo "[entrypoint] running migrations..."
alembic upgrade head
echo "[entrypoint] migrations done, starting: $*"
exec "$@"
