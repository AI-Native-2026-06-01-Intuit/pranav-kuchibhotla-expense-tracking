"""Idempotent pgvector loader for embedded corpus rows.

Callers construct ``CorpusRow`` values from ``expense_ai.corpus`` and hand
them to :func:`load_rows`, which will upsert on
``(doc_id, chunk_idx, model_version)`` so re-running the loader against the
same corpus is a no-op at the row-count level.
"""

from __future__ import annotations

import os
from collections.abc import Iterable

import psycopg
from pgvector.psycopg import register_vector

from .corpus import CorpusRow

_UPSERT_SQL = """
INSERT INTO doc_chunks
    (doc_id, chunk_idx, chunk_text, embedding, model_version, tenant_id)
VALUES (%s, %s, %s, %s, %s, %s)
ON CONFLICT (doc_id, chunk_idx, model_version) DO UPDATE
    SET chunk_text = EXCLUDED.chunk_text,
        embedding  = EXCLUDED.embedding,
        tenant_id  = EXCLUDED.tenant_id
"""


def dsn_from_env() -> str:
    """Return the pgvector DSN from ``EXPENSE_AI_PG_DSN`` or raise."""
    dsn = os.environ.get("EXPENSE_AI_PG_DSN")
    if not dsn:
        raise RuntimeError("EXPENSE_AI_PG_DSN is not set")
    return dsn


def load_rows(dsn: str, rows: Iterable[CorpusRow]) -> int:
    """Upsert ``rows`` into ``doc_chunks`` and return the count sent."""
    payload = [
        (
            row.doc_id,
            row.chunk_idx,
            row.chunk_text,
            row.embedding,
            row.model_version,
            row.tenant_id,
        )
        for row in rows
    ]
    if not payload:
        return 0

    with psycopg.connect(dsn) as conn:
        register_vector(conn)
        with conn.cursor() as cur:
            cur.executemany(_UPSERT_SQL, payload)
        conn.commit()
    return len(payload)
