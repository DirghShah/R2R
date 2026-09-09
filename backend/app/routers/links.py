"""Universal Links: the web half of an invite.

An invite link has to work for someone who doesn't have the app yet — that is
the whole growth loop. So the same URL either opens the app (via the
apple-app-site-association file below) or renders a page pointing at the App
Store.
"""
from __future__ import annotations

import html
import logging

from fastapi import APIRouter, Depends
from fastapi.responses import HTMLResponse, JSONResponse
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import settings
from app.db import get_db
from app.maps import member_count
from app.models import Map, User

log = logging.getLogger(__name__)

router = APIRouter(tags=["links"])


@router.get("/.well-known/apple-app-site-association", include_in_schema=False)
def apple_app_site_association() -> JSONResponse:
    """iOS fetches this over HTTPS to decide whether our links open the app.

    Must be served as JSON with no redirect and no .json extension, or iOS
    silently ignores it and every invite link opens Safari instead.
    """
    if not settings.apple_team_id:
        # Serving a placeholder team id is worse than serving nothing: iOS
        # fetches this once, caches the mismatch, and every invite link opens
        # Safari for good — with no error anywhere to explain why.
        log.error(
            "APPLE_TEAM_ID is not set — refusing to serve apple-app-site-association. "
            "Universal Links will not work until it is."
        )
        return JSONResponse(
            {"error": "APPLE_TEAM_ID is not configured on this server."},
            status_code=503,
            media_type="application/json",
        )

    app_id = f"{settings.apple_team_id}.{settings.apple_bundle_id}"
    return JSONResponse(
        {
            "applinks": {
                "apps": [],
                "details": [{"appID": app_id, "paths": ["/join/*"]}],
            }
        },
        media_type="application/json",
    )


@router.get("/join/{code}", response_class=HTMLResponse, include_in_schema=False)
def join_landing(code: str, db: Session = Depends(get_db)) -> HTMLResponse:
    """Fallback page for anyone without the app installed.

    With the app installed iOS intercepts this URL and never loads the page.
    """
    m = db.scalar(select(Map).where(Map.invite_code == code))
    if m is None:
        return HTMLResponse(_page("Invite not found",
                                  "That invite link is no longer valid."), status_code=404)

    owner = db.get(User, m.owner_id)
    who = owner.display_name if owner and owner.display_name else "Someone"
    people = member_count(db, m.id)
    title = f"{html.escape(m.emoji or '📍')} {html.escape(m.name)}"
    body = (
        f"{html.escape(who)} shared a Nosh map with you — "
        f"{people} {'person' if people == 1 else 'people'} so far."
    )
    return HTMLResponse(_page(title, body, show_store=True))


def _page(title: str, body: str, show_store: bool = False) -> str:
    store = (
        f'<a class="cta" href="{settings.app_store_url}">Get Nosh</a>'
        '<p class="hint">Already have it? Open this link on your iPhone.</p>'
        if show_store and settings.app_store_url
        else ""
    )
    return f"""<!doctype html>
<html lang="en"><head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>{title} · Nosh</title>
<style>
  :root {{ color-scheme: light dark; }}
  body {{ margin:0; min-height:100vh; display:grid; place-items:center;
         font:16px/1.5 -apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif;
         background:#F6F6F3; color:#16201C; padding:24px; }}
  @media (prefers-color-scheme: dark) {{ body {{ background:#111412; color:#F1F4F1; }} }}
  .card {{ max-width:26rem; text-align:center; }}
  h1 {{ font-size:1.6rem; margin:0 0 .5rem; }}
  p {{ color:#6B746F; margin:0 0 1.5rem; }}
  .cta {{ display:inline-block; background:#159A6A; color:#fff; text-decoration:none;
          padding:.85rem 1.6rem; border-radius:14px; font-weight:600; }}
  .hint {{ font-size:.85rem; margin-top:1rem; }}
</style></head>
<body><div class="card">
<h1>{title}</h1>
<p>{body}</p>
{store}
</div></body></html>"""
