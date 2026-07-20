"""Small helper for waiting on Testcontainers Postgres to become ready."""

from __future__ import annotations

import time

import psycopg


def wait_for_postgres(dsn: str, timeout: float = 30.0) -> None:
    """Block until a psycopg connection to ``dsn`` succeeds or ``timeout`` s."""
    deadline = time.monotonic() + timeout
    last_exc: Exception | None = None
    while time.monotonic() < deadline:
        try:
            with psycopg.connect(dsn, connect_timeout=2) as conn, conn.cursor() as cur:
                cur.execute("SELECT 1")
            return
        except psycopg.OperationalError as exc:
            last_exc = exc
            time.sleep(0.5)
    raise RuntimeError(f"Postgres at {dsn} not ready after {timeout}s: {last_exc}")
