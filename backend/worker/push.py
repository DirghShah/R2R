"""APNs push — no-ops cleanly when APNs isn't configured (e.g. local dev)."""
from __future__ import annotations

from sqlalchemy import select

from app.config import settings
from app.db import session
from app.models import Device


def notify_user(user_id: str, title: str, body: str, deep_link: str | None = None) -> None:
    if not (settings.apns_key_path and settings.apns_key_id and settings.apns_team_id):
        return  # not configured; skip silently in dev

    tokens = _device_tokens(user_id)
    if not tokens:
        return

    try:
        import asyncio

        from aioapns import APNs, NotificationRequest, PushType

        async def _send() -> None:
            apns = APNs(
                key=settings.apns_key_path,
                key_id=settings.apns_key_id,
                team_id=settings.apns_team_id,
                topic=settings.apns_topic,
                use_sandbox=settings.apns_use_sandbox,
            )
            payload = {"aps": {"alert": {"title": title, "body": body}, "sound": "default"}}
            if deep_link:
                payload["deep_link"] = deep_link
            for token in tokens:
                await apns.send_notification(
                    NotificationRequest(device_token=token, message=payload, push_type=PushType.ALERT)
                )

        asyncio.run(_send())
    except Exception:
        # Push failures must never fail the analysis job.
        pass


def _device_tokens(user_id: str) -> list[str]:
    db = session()
    try:
        return list(db.scalars(select(Device.apns_token).where(Device.user_id == user_id)))
    finally:
        db.close()
