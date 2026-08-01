"""Shared test configuration.

The important bit: SQLite ignores foreign keys unless explicitly told not to,
while Postgres always enforces them. Without this, a delete that leaves dangling
references passes every test and then 500s in production — which is exactly what
happened to `DELETE /me`.
"""
from __future__ import annotations

import pytest
from sqlalchemy import event


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
