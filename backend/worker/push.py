"""APNs push — no-ops cleanly when APNs isn't configured (e.g. local dev)."""
from __future__ import annotations

import logging

from sqlalchemy import select

from app.config import settings
from app.db import session
from app.models import Device

log = logging.getLogger(__name__)

# Apple retires a token when the app is deleted or restored onto a new device.
# Sending to it forever wastes calls, so we drop it on the documented replies.
_DEAD_TOKEN_REASONS = {"BadDeviceToken", "Unregistered", "DeviceTokenNotForTopic"}


def notify_user(user_id: str, title: str, body: str, deep_link: str | None = None) -> None:
    if not (settings.apns_key_path and settings.apns_key_id and settings.apns_team_id):
        log.debug("push: APNs not configured, skipping %r", title)
        return  # not configured; skip silently in dev

    tokens = _device_tokens(user_id)
    if not tokens:
        log.info("push: user %s has no registered devices", user_id)
        return

    try:
        import asyncio

        from aioapns import APNs, NotificationRequest, PushType

        async def _send() -> list[str]:
            apns = APNs(
                key=settings.apns_key_path,
                key_id=settings.apns_key_id,
                team_id=settings.apns_team_id,
                topic=settings.apns_topic,
                use_sandbox=settings.apns_use_sandbox,
            )
            payload = {
                "aps": {
                    "alert": {"title": title, "body": body},
                    "sound": "default",
                    # Collapse repeated shares into one stack rather than a
                    # column of near-identical banners.
                    "thread-id": "reel-analysis",
                }
            }
            if deep_link:
                payload["deep_link"] = deep_link

            dead: list[str] = []
            for token in tokens:
                try:
                    result = await apns.send_notification(
                        NotificationRequest(device_token=token, message=payload,
                                            push_type=PushType.ALERT)
                    )
                except Exception:  # noqa: BLE001 — one bad token must not stop the rest
                    log.warning("push: send failed for a device", exc_info=True)
                    continue
                if getattr(result, "description", None) in _DEAD_TOKEN_REASONS:
                    dead.append(token)
            return dead

        dead = asyncio.run(_send())
        if dead:
            _forget_tokens(dead)
    except Exception:
        # Push failures must never fail the analysis job.
        log.warning("push: notify_user failed", exc_info=True)


def _forget_tokens(tokens: list[str]) -> None:
    db = session()
    try:
        for device in db.scalars(select(Device).where(Device.apns_token.in_(tokens))):
            db.delete(device)
        db.commit()
        log.info("push: dropped %d dead device token(s)", len(tokens))
    except Exception:  # noqa: BLE001
        log.warning("push: could not drop dead tokens", exc_info=True)
    finally:
        db.close()


def _device_tokens(user_id: str) -> list[str]:
    db = session()
    try:
        return list(db.scalars(select(Device.apns_token).where(Device.user_id == user_id)))
    finally:
        db.close()
