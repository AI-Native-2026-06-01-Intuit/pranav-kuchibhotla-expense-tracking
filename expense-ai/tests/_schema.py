"""Test helpers for applying V001 and V002 migrations to a pgvector DB.

``CREATE INDEX CONCURRENTLY`` cannot run inside a transaction block, so V002
is applied statement-by-statement with autocommit enabled. V001 has no such
constraint and runs in a normal transaction.
"""

from __future__ import annotations

import re
from pathlib import Path

import psycopg

_SQL_DIR = Path(__file__).resolve().parent.parent / "sql"
_V001_PATH = _SQL_DIR / "V001__doc_chunks.sql"
_V002_PATH = _SQL_DIR / "V002__rag2_metadata_and_partial_indexes.sql"

_STATEMENT_SPLIT = re.compile(r";\s*(?:\n|$)")


def _split_statements(sql: str) -> list[str]:
    stripped = re.sub(r"--[^\n]*\n", "\n", sql)
    parts = [s.strip() for s in _STATEMENT_SPLIT.split(stripped)]
    return [p for p in parts if p]


def apply_v001(dsn: str) -> None:
    ddl = _V001_PATH.read_text()
    with psycopg.connect(dsn) as conn:
        with conn.cursor() as cur:
            cur.execute(ddl)
        conn.commit()


def apply_v002(dsn: str) -> None:
    """Apply V002 with autocommit so CREATE INDEX CONCURRENTLY works."""
    ddl = _V002_PATH.read_text()
    statements = _split_statements(ddl)
    conn = psycopg.connect(dsn, autocommit=True)
    try:
        with conn.cursor() as cur:
            for stmt in statements:
                cur.execute(stmt)
    finally:
        conn.close()


def apply_all(dsn: str) -> None:
    apply_v001(dsn)
    apply_v002(dsn)
