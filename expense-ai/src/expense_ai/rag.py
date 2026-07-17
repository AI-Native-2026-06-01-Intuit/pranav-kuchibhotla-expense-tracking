"""LangSmith-traceable pgvector retrieval for the expense-ai RAG path."""

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Protocol, cast

import numpy as np
import psycopg
from langsmith import traceable
from numpy.typing import NDArray
from pgvector.psycopg import register_vector

from .corpus import EMBEDDING_DIM, MODEL_NAME

_ALLOW_SKIP_ENV = "EXPENSE_AI_ALLOW_EXTERNAL_SKIP"
_API_KEY_ENV = "LANGSMITH_API_KEY"

_RETRIEVE_SQL = """
SELECT doc_id, chunk_idx, chunk_text, embedding <=> %s AS distance
FROM doc_chunks
WHERE tenant_id = %s AND model_version = %s
ORDER BY embedding <=> %s
LIMIT %s
"""


@dataclass(frozen=True, slots=True)
class RetrievedChunk:
    """One retrieved doc chunk from the pgvector store."""

    doc_id: str
    chunk_idx: int
    chunk_text: str
    distance: float


class _EncoderLike(Protocol):
    """Structural type matching what we call on SentenceTransformer."""

    def encode(
        self,
        sentences: list[str],
        batch_size: int = ...,
        normalize_embeddings: bool = ...,
        convert_to_numpy: bool = ...,
    ) -> NDArray[np.float32]: ...


def _require_langsmith_auth() -> None:
    if os.environ.get(_API_KEY_ENV):
        return
    if os.environ.get(_ALLOW_SKIP_ENV) == "1":
        return
    raise RuntimeError(
        f"{_API_KEY_ENV} is required for LangSmith-traced retrieval; "
        f"set {_ALLOW_SKIP_ENV}=1 for local dry-runs"
    )


def _embed_query(question: str, model: _EncoderLike | None) -> NDArray[np.float32]:
    if model is None:
        from sentence_transformers import SentenceTransformer

        model = cast(_EncoderLike, SentenceTransformer(MODEL_NAME))
    raw = model.encode(
        [question],
        batch_size=1,
        normalize_embeddings=True,
        convert_to_numpy=True,
    )
    matrix = np.asarray(raw, dtype=np.float32)
    if matrix.shape != (1, EMBEDDING_DIM):
        raise ValueError(f"Query embedding shape {matrix.shape} != (1, {EMBEDDING_DIM})")
    row: NDArray[np.float32] = matrix[0].astype(np.float32, copy=False)
    return row


@traceable(run_type="retriever", name="expense_ai.retrieve_chunks")
def retrieve_chunks(
    dsn: str,
    question: str,
    k: int = 5,
    tenant_id: str = "tenant-a",
    model_version: str = MODEL_NAME,
    model: _EncoderLike | None = None,
) -> list[RetrievedChunk]:
    """Top-k pgvector cosine retrieval, traced by LangSmith."""
    _require_langsmith_auth()
    query_vec = _embed_query(question, model)

    with psycopg.connect(dsn) as conn:
        register_vector(conn)
        with conn.cursor() as cur:
            cur.execute(
                _RETRIEVE_SQL,
                (query_vec, tenant_id, model_version, query_vec, k),
            )
            rows = cur.fetchall()

    return [
        RetrievedChunk(
            doc_id=str(r[0]),
            chunk_idx=int(r[1]),
            chunk_text=str(r[2]),
            distance=float(r[3]),
        )
        for r in rows
    ]
