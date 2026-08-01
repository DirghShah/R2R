"""RQ worker entrypoint.

Started as `python -m worker.run` rather than the `rq` CLI on purpose.

A platform start command like `rq worker --url $REDIS_URL reels` is handed to
the container as an argument vector, not a shell line — so `$REDIS_URL` arrives
as that literal string, and the worker dies trying to resolve a host named
"$REDIS_URL". Reading the URL from `app.config` removes the expansion problem
entirely and keeps one source of truth for the connection settings.
"""
from __future__ import annotations

import logging

from redis import Redis
from rq import Queue, Worker

from app.config import settings

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
log = logging.getLogger("worker")

QUEUE_NAME = "reels"


def main() -> None:
    # Redact credentials before logging the URL.
    safe = settings.redis_url
    if "@" in safe:
        safe = safe.split("@", 1)[1]
    log.info("connecting to redis at %s", safe)

    connection = Redis.from_url(settings.redis_url)
    try:
        connection.ping()  # fail here, with an explanation, not mid-job
    except Exception as exc:  # noqa: BLE001
        log.error("cannot reach redis: %s", exc)
        log.error(
            "Set REDIS_URL on THIS service. On Railway that means a reference: "
            "REDIS_URL=${{Redis.REDIS_URL}} — adding the Redis plugin does not "
            "expose it to other services."
        )
        raise SystemExit(1) from exc

    log.info("redis ok — listening on %r", QUEUE_NAME)
    worker = Worker([Queue(QUEUE_NAME, connection=connection)], connection=connection)
    worker.work()


if __name__ == "__main__":
    main()
