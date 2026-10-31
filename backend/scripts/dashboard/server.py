#!/usr/bin/env python3
"""Local dashboard for the Nosh ops stats.

    server.py                    # live, http://127.0.0.1:8765
    server.py --demo             # made-up numbers, to try the layout
    server.py --snapshot out.html            # one static file with today's numbers
    server.py --snapshot out.html --investor # same, minus bills/config/ledger

Needs NOSH_API and NOSH_ADMIN_TOKEN (see scripts/nosh_stats.py). The token stays
in this process: the page only ever talks to this server, never to the API, so
it can't leak into the browser or into a shared file.

Standard library only. Binds to 127.0.0.1; this is not meant to be deployed.
"""
from __future__ import annotations

import argparse
import json
import os
import random
import sys
import urllib.error
import urllib.request
from datetime import datetime, timedelta, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

HERE = Path(__file__).parent


def upstream(path: str) -> dict:
    base = os.environ.get("NOSH_API", "").rstrip("/")
    token = os.environ.get("NOSH_ADMIN_TOKEN", "")
    if not base or not token:
        sys.exit("Set NOSH_API and NOSH_ADMIN_TOKEN first.")
    req = urllib.request.Request(f"{base}{path}", headers={"Authorization": f"Bearer {token}"})
    with urllib.request.urlopen(req, timeout=30) as resp:
        return json.loads(resp.read())


def load_config() -> dict:
    for name in ("config.json", "config.example.json"):
        p = HERE / name
        if p.exists():
            return json.loads(p.read_text())
    return {}


def demo_data() -> tuple[dict, dict]:
    """Plausible numbers shaped exactly like the real endpoints. Seeded so the
    screenshot doesn't change between runs."""
    rnd = random.Random(7)
    now = datetime.now(timezone.utc)
    reels = []
    for i in range(160):
        t = now - timedelta(days=29 * (1 - (rnd.random() ** 0.6)), minutes=rnd.randint(0, 1400))
        places = rnd.choice([0, 2, 3, 4, 5, 5, 6, 8])
        claude, fetch, geo = round(rnd.uniform(.012, .03), 4), 0.005, round(places * .067 * rnd.choice([0, 1, 1]), 4)
        reels.append({"id": f"demo{i}", "platform": "instagram", "status": "done" if places else "unsupported",
                      "created_at": t.isoformat(), "places": places, "claude_usd": claude, "fetch_usd": fetch,
                      "geocode_usd": geo, "cost_usd": round(claude + fetch + geo, 4)})
    reels.sort(key=lambda r: r["created_at"], reverse=True)
    v = {k: round(sum(r[f"{k}_usd"] for r in reels), 4) for k in ("claude", "fetch", "geocode")}
    v["unattributed"] = 0.0
    total = round(sum(v.values()), 2)
    month = round(total * .85, 2)
    fixed_items = [{"name": "Apple Developer Program", "usd": 99.0, "period": "annual"},
                   {"name": "Railway hosting", "usd": 20.0, "period": "monthly"},
                   {"name": "noshmap.app domain", "usd": 20.0, "period": "annual"}]
    fixed = {"items": fixed_items, "monthly_equivalent": 30.0, "annual_equivalent": 359.0, "one_time_total": 0.0}
    stats = {
        "__demo": True, "generated_at": now.isoformat(),
        "users": {"total": 214, "new_24h": 9, "new_30d": 131},
        "reels": {"total": 160, "by_status": {"done": 131, "unsupported": 29}, "last_24h": 11, "last_30d": 160, "stuck": 0},
        "places": {"canonical": 612, "saved": 1043, "maps": 188, "shared_maps": 14},
        "config": {"environment": "production", "claude_model": "claude-haiku-4-5", "reel_fetcher": "apify",
                   "geocoder": "google", "free_monthly_reel_limit": 50},
        "cost_usd": {"last_24h": 0.9, "last_30d": month, "all_time": total,
                     "avg_per_reel_30d": round(month / 160, 4), "by_vendor_all_time": v, "fixed": fixed,
                     "total_monthly_estimate": round(30 + month, 2)},
        "cache": {"places_from_cache": 301, "places_looked_up": 311, "hit_rate": 0.492, "saved_usd": 20.17},
        "growth": demo_growth(now),
        "unit_economics": {"cost_of_a_maxed_free_user_monthly": round(month / 160 * 50, 2),
                           "avg_places_per_reel": 4.7, "share_of_reels_with_no_places": 0.181},
    }
    return stats, {"total": len(reels), "limit": 500, "offset": 0, "reels": reels}


def demo_growth(now: datetime) -> dict:
    rnd = random.Random(11)
    monday = (now - timedelta(days=now.weekday())).date()
    weekly = []
    for i in range(7, -1, -1):
        signups = rnd.randint(6, 26)
        act = round(signups * rnd.uniform(.38, .62))
        elig = signups if i >= 1 else 0
        weekly.append({"week_start": (monday - timedelta(weeks=i)).isoformat(), "signups": signups,
                       "activated": act, "activated_day_one": round(act * .7), "only_tried_example": 2,
                       "d7_eligible": elig, "d7_retained": round(elig * rnd.uniform(.18, .34)),
                       "invites_accepted": rnd.randint(0, 6), "maps_created": rnd.randint(1, 9)})
    tot = lambda k: sum(w[k] for w in weekly)  # noqa: E731
    return {"overall": {k: tot(k) for k in ("signups", "activated", "activated_day_one", "only_tried_example",
                                             "d7_eligible", "d7_retained")},
            "weekly": weekly,
            "sharing": {"maps_created": 188, "invite_links_created": 41, "shared_maps": 14,
                        "invites_accepted": tot("invites_accepted"), "invites_accepted_30d": 17},
            "example_configured": True,
            "d7_basis": "adds a reel, saves a place, joins a map or reopens the app 7+ days after signup"}


class Handler(BaseHTTPRequestHandler):
    demo = False

    def log_message(self, *a):  # quiet
        pass

    def _send(self, body: bytes, ctype: str, code: int = 200) -> None:
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def _json(self, obj: dict, code: int = 200) -> None:
        self._send(json.dumps(obj).encode(), "application/json", code)

    def do_GET(self) -> None:
        path = self.path.split("?")[0]
        if path in ("/", "/index.html"):
            return self._send((HERE / "index.html").read_bytes(), "text/html; charset=utf-8")
        if path == "/api/config":
            cfg = load_config()
            if self.demo:
                cfg = {**cfg, "manual": {**cfg.get("manual", {}), "downloads": 412,
                       "downloads_note": "Demo numbers",
                       "downloads_by_channel": {"Instagram": 168, "TikTok": 121, "Friends / invites": 74, "App Store search": 49}}}
            return self._json(cfg)
        if path in ("/api/stats", "/api/reels"):
            try:
                if self.demo:
                    stats, ledger = demo_data()
                    return self._json(stats if path == "/api/stats" else ledger)
                qs = self.path.partition("?")[2]
                return self._json(upstream("/admin/stats" if path == "/api/stats" else f"/admin/reels?{qs}"))
            except urllib.error.HTTPError as e:
                msg = "404: check NOSH_ADMIN_TOKEN matches ADMIN_TOKEN on the service" if e.code == 404 else f"upstream {e.code}"
                return self._json({"error": msg}, 502)
            except (urllib.error.URLError, OSError) as e:
                return self._json({"error": f"couldn't reach the API: {e}"}, 502)
        self._send(b"not found", "text/plain", 404)


def snapshot(out: str, investor: bool) -> None:
    stats, ledger, cfg = upstream("/admin/stats"), upstream("/admin/reels?limit=500"), load_config()
    if investor:
        # Shared files get aggregates only: no bills, no per-reel ledger, no
        # vendor config. Stuck-reel and model details are ops noise to outsiders.
        cfg = {"manual": cfg.get("manual", {})}
        ledger = {"total": ledger["total"], "limit": 500, "offset": 0,
                  "reels": [{"created_at": r["created_at"], "status": r["status"]} for r in ledger["reels"]]}
        stats["config"] = {"free_monthly_reel_limit": stats["config"]["free_monthly_reel_limit"]}
        stats["reels"]["stuck"] = 0
    blob = json.dumps({"stats": stats, "ledger": ledger, "config": cfg, "investor": investor})
    safe = blob.replace("</", "<\\/")
    html = (HERE / "index.html").read_text().replace(
        "<script>\nconst $", "<script>window.__SNAPSHOT__ = " + safe + ";</script>\n<script>\nconst $", 1)
    Path(out).write_text(html)
    print(f"Wrote {out} ({'investor' if investor else 'full'} snapshot).")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--demo", action="store_true")
    ap.add_argument("--port", type=int, default=int(os.environ.get("PORT", 8765)))
    ap.add_argument("--snapshot", metavar="FILE")
    ap.add_argument("--investor", action="store_true")
    a = ap.parse_args()
    if a.snapshot:
        return snapshot(a.snapshot, a.investor)
    Handler.demo = a.demo
    print(f"Nosh dashboard{' (demo data)' if a.demo else ''}: http://127.0.0.1:{a.port}")
    ThreadingHTTPServer(("127.0.0.1", a.port), Handler).serve_forever()


if __name__ == "__main__":
    main()
