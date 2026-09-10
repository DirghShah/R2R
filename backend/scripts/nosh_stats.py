#!/usr/bin/env python3
"""Read the ops stats and print them as something a person can read.

    nosh_stats.py                 # the summary
    nosh_stats.py --reels         # every reel analysed, newest first
    nosh_stats.py --reels --csv   # the same, for a spreadsheet
    nosh_stats.py --json          # raw, for piping

Needs two environment variables:

    NOSH_API=https://your-service.up.railway.app
    NOSH_ADMIN_TOKEN=<the ADMIN_TOKEN set on the service>

Standard library only, so it runs anywhere Python does without a virtualenv.
A dashboard would be a nicer demo, but it is a login, a session and a deploy
target built for an audience of one — and the CSV out of here is what actually
goes in front of anybody else.
"""
from __future__ import annotations

import argparse
import csv
import json
import os
import sys
import urllib.error
import urllib.request


def fetch(path: str) -> dict:
    base = os.environ.get("NOSH_API", "").rstrip("/")
    token = os.environ.get("NOSH_ADMIN_TOKEN", "")
    if not base or not token:
        sys.exit("Set NOSH_API and NOSH_ADMIN_TOKEN first.")
    req = urllib.request.Request(
        f"{base}{path}", headers={"Authorization": f"Bearer {token}"}
    )
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            return json.loads(resp.read())
    except urllib.error.HTTPError as exc:
        if exc.code == 404:
            # The endpoint 404s rather than 401s when the token is wrong, so
            # that a stranger can't confirm it exists. Which means a 404 here is
            # almost always a bad token, not a bad path.
            sys.exit("404 — check NOSH_ADMIN_TOKEN matches ADMIN_TOKEN on the service.")
        sys.exit(f"HTTP {exc.code}: {exc.read()[:200].decode(errors='replace')}")
    except urllib.error.URLError as exc:
        sys.exit(f"Couldn't reach {base}: {exc.reason}")


def money(v: float | None) -> str:
    """Dollars, for totals."""
    return "—" if v is None else f"${v:,.2f}"


def micro(v: float | None) -> str:
    """Four decimals, for the per-reel figures where $0.0565 rounding to $0.06
    loses the only precision anyone cares about. Zeros are kept so the numbers
    line up in a column."""
    return "—" if v is None else f"${v:,.4f}"


def rule(title: str = "") -> None:
    print(f"\n{title}\n" + "─" * 58 if title else "─" * 58)


def summary(d: dict) -> None:
    cfg, cost, reels = d["config"], d["cost_usd"], d["reels"]
    fixed, unit = cost["fixed"], d["unit_economics"]

    rule("CONFIGURATION")
    for k, v in cfg.items():
        print(f"  {k.replace('_', ' '):<26} {v}")

    rule("USAGE")
    u = d["users"]
    print(f"  {'users':<26} {u['total']}  (+{u['new_30d']} in 30d, +{u['new_24h']} today)")
    print(f"  {'reels analysed':<26} {reels['total']}  (+{reels['last_30d']} in 30d, "
          f"+{reels['last_24h']} today)")
    for status, n in sorted(reels["by_status"].items()):
        print(f"    {status:<24} {n}")
    if reels["stuck"]:
        print(f"  {'STUCK (worker died)':<26} {reels['stuck']}")
    p = d["places"]
    print(f"  {'places (canonical)':<26} {p['canonical']}")
    print(f"  {'places saved by users':<26} {p['saved']}")
    print(f"  {'maps':<26} {p['maps']}  ({p['shared_maps']} shared)")

    rule("VARIABLE COST — per reel")
    for vendor, amount in cost["by_vendor_all_time"].items():
        share = amount / cost["all_time"] * 100 if cost["all_time"] else 0
        print(f"  {vendor:<26} {money(amount):>10}   {share:5.1f}%")
    print(f"  {'':<26} {'─' * 10}")
    print(f"  {'all time':<26} {money(cost['all_time']):>10}")
    print(f"  {'last 30 days':<26} {money(cost['last_30d']):>10}")
    print(f"  {'average per reel':<26} {micro(cost['avg_per_reel_30d']):>10}")

    cache = d.get("cache")
    if cache and (cache["places_from_cache"] or cache["places_looked_up"]):
        rule("PLACE CACHE — restaurants we didn't pay to look up twice")
        print(f"  {'reused from the database':<26} {cache['places_from_cache']:>10}")
        print(f"  {'looked up (billed)':<26} {cache['places_looked_up']:>10}")
        print(f"  {'hit rate':<26} {cache['hit_rate'] * 100:>9.1f}%")
        print(f"  {'saved so far':<26} {money(cache['saved_usd']):>10}")

    rule("FIXED COST — per month")
    for item in fixed["items"]:
        per_month = item["usd"] / 12 if item["period"] == "annual" else item["usd"]
        note = "" if item["period"] == "monthly" else f"  ({money(item['usd'])}/{item['period']})"
        if item["period"] == "once":
            per_month = 0.0
        print(f"  {item['name']:<26} {money(per_month):>10}{note}")
    print(f"  {'':<26} {'─' * 10}")
    print(f"  {'monthly':<26} {money(fixed['monthly_equivalent']):>10}")
    print(f"  {'annual':<26} {money(fixed['annual_equivalent']):>10}")
    if fixed["one_time_total"]:
        print(f"  {'one-off (not amortised)':<26} {money(fixed['one_time_total']):>10}")

    rule("TOTAL — last 30 days")
    print(f"  {'fixed + variable':<26} {money(cost['total_monthly_estimate']):>10}")

    rule("UNIT ECONOMICS")
    print(f"  {'avg places per reel':<26} {unit['avg_places_per_reel']:>10}")
    print(f"  {'reels with nothing to pin':<26} "
          f"{unit['share_of_reels_with_no_places'] * 100:>9.1f}%")
    print(f"  {'a maxed free user costs':<26} "
          f"{money(unit['cost_of_a_maxed_free_user_monthly']):>10} / month")
    print()


REEL_COLUMNS = [
    "created_at", "platform", "status", "places", "model",
    "input_tokens", "output_tokens", "claude_usd", "fetch_usd", "geocode_usd",
    "cost_usd", "seconds", "id",
]


def ledger(rows: list[dict], as_csv: bool) -> None:
    if as_csv:
        w = csv.DictWriter(sys.stdout, fieldnames=REEL_COLUMNS, extrasaction="ignore")
        w.writeheader()
        w.writerows(rows)
        return
    print(f"{'when':<17}{'plat':<11}{'status':<13}{'pl':>3}"
          f"{'in tok':>9}{'out':>7}{'cost':>10}  model")
    print("─" * 96)
    for r in rows:
        when = (r["created_at"] or "")[:16].replace("T", " ")
        print(f"{when:<17}{r['platform']:<11}{r['status']:<13}"
              f"{r['places'] if r['places'] is not None else '—':>3}"
              f"{r['input_tokens'] or 0:>9}{r['output_tokens'] or 0:>7}"
              f"{micro(r['cost_usd']):>10}  {r['model'] or '—'}")
    total = sum(r["cost_usd"] or 0 for r in rows)
    print("─" * 96)
    print(f"{len(rows)} reels, {money(round(total, 4))}")


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--reels", action="store_true", help="per-reel ledger instead of the summary")
    ap.add_argument("--csv", action="store_true", help="CSV, for a spreadsheet")
    ap.add_argument("--json", action="store_true", help="raw JSON")
    ap.add_argument("--limit", type=int, default=500)
    ap.add_argument("--status", help="only reels with this status")
    args = ap.parse_args()

    if args.reels:
        path = f"/admin/reels?limit={args.limit}"
        if args.status:
            path += f"&status={args.status}"
        data = fetch(path)
        if args.json:
            print(json.dumps(data, indent=2))
        else:
            ledger(data["reels"], args.csv)
        return

    data = fetch("/admin/stats")
    if args.json or args.csv:
        print(json.dumps(data, indent=2))
    else:
        summary(data)


if __name__ == "__main__":
    main()
