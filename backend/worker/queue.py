"""RQ job queue wiring."""
from __future__ import annotations

from redis import Redis
from rq import Queue

from app.config import settings

redis_conn = Redis.from_url(settings.redis_url)
reel_queue = Queue("reels", connection=redis_conn)


def enqueue_analyze(reel_id: str, user_id: str) -> str:
    job = reel_queue.enqueue("worker.pipeline.analyze_reel", reel_id, user_id, job_timeout=600)
    return job.id
