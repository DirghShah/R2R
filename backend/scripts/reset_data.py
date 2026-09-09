"""Delete every row, keeping the schema. Irreversible.

For starting from a genuinely clean state — most usefully before taking App
Store screenshots, where leftover test pins and half-broken places are visible
in the one asset most people judge the app by.

This is not a routine operation. It deletes every user, every map, and every
saved place, including other people's. It also drops the reel analysis cache,
which is the part that costs money: a reel already analysed is normally free to
re-add, and after this it is not.

Guarded three ways: it refuses without --yes, refuses in prod without
--i-understand-this-is-production, and prints what it is about to delete first.

    python -m scripts.reset_data                     # dry run, prints counts
    python -m scripts.reset_data --yes               # dev
    python -m scripts.reset_data --yes --i-understand-this-is-production
"""
from __future__ import annotations

import argparse
import sys

from sqlalchemy import func, select

from app.config import settings
from app.db import session
from app.models import (
    Block,
    City,
    Collection,
    Device,
    Map,
    MapMember,
    Place,
    RefreshToken,
    ReelSource,
    Report,
    User,
    UserPlace,
    UserReel,
)

# Children before parents. TRUNCATE CASCADE would be shorter, but it is not
# portable to the SQLite used by the tests, and naming the order makes it
# obvious what exists — a table added later and forgotten here fails loudly on
# a foreign key rather than silently surviving the reset.
ORDER = [
    Block, Report, UserReel, UserPlace, Collection,
    MapMember, Map, Device, RefreshToken, User,
    ReelSource, Place, City,
]


def counts(db) -> dict[str, int]:
    return {
        m.__tablename__: db.scalar(select(func.count()).select_from(m)) or 0
        for m in ORDER
    }


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--yes", action="store_true", help="actually delete")
    ap.add_argument("--i-understand-this-is-production", action="store_true")
    args = ap.parse_args()

    db = session()
    try:
        before = counts(db)
        total = sum(before.values())

        print(f"environment: {settings.environment}")
        print(f"database:    {settings.database_url.split('@')[-1]}")
        print()
        for table, n in before.items():
            print(f"  {table:<16} {n:>6}")
        print(f"  {'TOTAL':<16} {total:>6}")
        print()

        if total == 0:
            print("Already empty. Nothing to do.")
            return 0

        if not args.yes:
            print("Dry run. Re-run with --yes to delete all of the above.")
            return 0

        if settings.environment == "prod" and not args.i_understand_this_is_production:
            print("Refusing: this is production.", file=sys.stderr)
            print("Add --i-understand-this-is-production if you mean it.", file=sys.stderr)
            return 1

        for model in ORDER:
            db.query(model).delete(synchronize_session=False)
        db.commit()

        after = sum(counts(db).values())
        print(f"Deleted {total} rows. {after} remain.")
        print()
        print("Next: every device is now signed in as a user that no longer")
        print("exists. The app will 401, fail to refresh, and show the sign-in")
        print("screen — signing in again creates a fresh account and a new")
        print("personal map. The local cache self-heals on the next sync.")
        return 0
    finally:
        db.close()


if __name__ == "__main__":
    raise SystemExit(main())
