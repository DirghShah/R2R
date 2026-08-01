"""Mint an access token for a test account, from inside the running container.

Run it in Railway's **Console** tab:

    python scripts/dev_token.py

Why this exists: `ENVIRONMENT=prod` rejects `dev:` identity tokens, which is
correct — that backdoor would let anyone who finds the URL authenticate as
anyone. Flipping to `dev` just to smoke-test the API would open exactly the hole
the setting is there to close. This mints a token for a clearly-labelled test
user without touching that setting.

The user is reused across runs, so repeated calls don't litter the database.
Clean it up when you're done:

    python scripts/dev_token.py --delete
"""
from __future__ import annotations

import os
import sys

# Run as `python scripts/dev_token.py` from the app root, so make the package
# importable without needing PYTHONPATH set.
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from sqlalchemy import select  # noqa: E402

from app.auth import create_access_token, issue_refresh_token  # noqa: E402
from app.db import session  # noqa: E402
from app.models import User  # noqa: E402

TEST_APPLE_SUB = "smoketest:local"


def main() -> None:
    delete = "--delete" in sys.argv
    db = session()
    try:
        user = db.scalar(select(User).where(User.apple_sub == TEST_APPLE_SUB))

        if delete:
            if user is None:
                print("No smoke-test user to delete.")
                return
            print(f"Deleting smoke-test user {user.id} — use DELETE /me from the "
                  f"API instead if you want its maps and places cleaned up too.")
            db.delete(user)
            db.commit()
            return

        if user is None:
            user = User(apple_sub=TEST_APPLE_SUB, display_name="Smoke Test",
                        avatar_color="#159A6A")
            db.add(user)
            db.commit()
            db.refresh(user)
            print(f"Created smoke-test user {user.id}")
        else:
            print(f"Reusing smoke-test user {user.id}")

        print()
        print("ACCESS TOKEN (valid 24h):")
        print(create_access_token(user.id))
        print()
        print("REFRESH TOKEN:")
        print(issue_refresh_token(db, user.id))
    finally:
        db.close()


if __name__ == "__main__":
    main()
