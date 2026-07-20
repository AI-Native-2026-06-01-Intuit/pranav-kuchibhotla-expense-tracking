"""Idempotent pgvector loader for embedded corpus rows.

Callers construct ``CorpusRow`` values from ``expense_ai.corpus`` and hand
them to :func:`load_rows`, which upserts on
``(doc_id, chunk_idx, model_version)`` so re-running the loader against the
same corpus is a no-op at the row-count level.

W7D3 additions:
  * ``RagChunkRow`` — extends ``CorpusRow`` with ``chunk_metadata`` (jsonb)
    and ``content_hash`` (sha256 hex).
  * :func:`load_rag_rows` — upserts the extended shape.
  * :func:`needs_embedding` — pre-embed gate. Returns False when the stored
    ``(model_version, content_hash)`` for the row matches, saving the model
    call. DB ON CONFLICT still handles idempotent writes.
"""

from __future__ import annotations

import hashlib
import json
import os
from collections.abc import Iterable, Mapping
from dataclasses import dataclass

import numpy as np
import psycopg
from numpy.typing import NDArray
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

_RAG_UPSERT_SQL = """
INSERT INTO doc_chunks
    (doc_id, chunk_idx, chunk_text, embedding, model_version, tenant_id,
     chunk_metadata, content_hash)
VALUES (%s, %s, %s, %s, %s, %s, %s::jsonb, %s)
ON CONFLICT (doc_id, chunk_idx, model_version) DO UPDATE
    SET chunk_text     = EXCLUDED.chunk_text,
        embedding      = EXCLUDED.embedding,
        tenant_id      = EXCLUDED.tenant_id,
        chunk_metadata = EXCLUDED.chunk_metadata,
        content_hash   = EXCLUDED.content_hash
"""


def dsn_from_env() -> str:
    """Return the pgvector DSN from ``EXPENSE_AI_PG_DSN`` or raise."""
    dsn = os.environ.get("EXPENSE_AI_PG_DSN")
    if not dsn:
        raise RuntimeError("EXPENSE_AI_PG_DSN is not set")
    return dsn


def content_hash_for_text(text: str) -> str:
    """Return a stable sha256 hex digest of ``text`` (chunk-level content)."""
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


@dataclass(frozen=True, slots=True)
class RagChunkRow:
    """One embedded chunk with W7D3 metadata/content_hash columns."""

    doc_id: str
    chunk_idx: int
    chunk_text: str
    embedding: NDArray[np.float32]
    model_version: str
    tenant_id: str
    chunk_metadata: Mapping[str, str]
    content_hash: str


def load_rows(dsn: str, rows: Iterable[CorpusRow]) -> int:
    """Upsert W7D2 ``CorpusRow`` values into ``doc_chunks``.

    Preserves the pre-W7D3 shape (no metadata/content_hash). Kept intact so
    existing loader tests remain green.
    """
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


def load_rag_rows(dsn: str, rows: Iterable[RagChunkRow]) -> int:
    """Upsert W7D3 rows (with chunk_metadata + content_hash) into ``doc_chunks``."""
    payload = [
        (
            row.doc_id,
            row.chunk_idx,
            row.chunk_text,
            row.embedding,
            row.model_version,
            row.tenant_id,
            json.dumps(dict(row.chunk_metadata)),
            row.content_hash,
        )
        for row in rows
    ]
    if not payload:
        return 0

    with psycopg.connect(dsn) as conn:
        register_vector(conn)
        with conn.cursor() as cur:
            cur.executemany(_RAG_UPSERT_SQL, payload)
        conn.commit()
    return len(payload)


def needs_embedding(
    conn: psycopg.Connection[psycopg.rows.TupleRow],
    doc_id: str,
    chunk_idx: int,
    model_version: str,
    content_hash: str,
) -> bool:
    """Return True if the chunk must be (re-)embedded.

    False when a row already exists for ``(doc_id, chunk_idx, model_version)``
    with a matching ``content_hash``. This is the model-call-saving gate;
    the DB upsert remains idempotent regardless.
    """
    with conn.cursor() as cur:
        cur.execute(
            "SELECT content_hash FROM doc_chunks "
            "WHERE doc_id = %s AND chunk_idx = %s AND model_version = %s",
            (doc_id, chunk_idx, model_version),
        )
        row = cur.fetchone()
    if row is None:
        return True
    stored = row[0]
    if stored is None:
        return True
    return str(stored) != content_hash
