"""Shared test configuration.

The important bit: SQLite ignores foreign keys unless explicitly told not to,
while Postgres always enforces them. Without this, a delete that leaves dangling
references passes every test and then 500s in production — which is exactly what
happened to `DELETE /me`.
"""
from __future__ import annotations

import os

import pytest
from sqlalchemy import event

# Every test signs in with a "dev:" token, which the API now refuses unless
# told otherwise. Set before anything imports app.config, whose settings are
# read once at import.
os.environ.setdefault("ALLOW_DEV_SIGN_IN", "true")


@pytest.fixture(scope="session", autouse=True)
def _enforce_sqlite_foreign_keys() -> None:
    """Make SQLite behave like Postgres about referential integrity."""
    from app.db import engine

    if engine.dialect.name != "sqlite":
        return

    @event.listens_for(engine, "connect")
    def _set_pragma(dbapi_connection, _connection_record):  # noqa: ANN001
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()
