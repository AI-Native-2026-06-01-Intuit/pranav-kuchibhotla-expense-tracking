"""LangSmith-traceable pgvector retrieval for the expense-ai RAG path.

W7D3 additions:
  * :func:`retrieve_and_generate` — end-to-end RAG entrypoint that combines
    the semantic cache, dense retrieval, hybrid FTS + RRF fusion, MMR
    diversification, and BGE reranking (each toggleable) before handing
    context to an injected Anthropic client.
"""

from __future__ import annotations

import os
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Protocol, cast

import numpy as np
import psycopg
import redis
from langsmith import traceable
from numpy.typing import NDArray
from pgvector.psycopg import register_vector

from .cache import cache_lookup, cache_store
from .corpus import EMBEDDING_DIM, MODEL_NAME
from .hybrid import (
    HybridHit,
    dense_topk_filtered,
    rrf_fuse,
    sparse_topk_fts,
)
from .rerank import bge_rerank, mmr_pick

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


class _AnthropicLike(Protocol):
    """Structural type matching the injected Anthropic client we use."""

    class _Messages(Protocol):
        def create(
            self,
            *,
            model: str,
            max_tokens: int,
            messages: list[dict[str, str]],
        ) -> object: ...

    @property
    def messages(self) -> _Messages: ...


def _env_flag(name: str, explicit: bool) -> bool:
    raw = os.environ.get(name)
    if raw is None:
        return explicit
    return raw.strip().lower() in {"1", "true", "yes", "on"}


def _feature_flags(
    *,
    use_hybrid: bool,
    use_mmr: bool,
    use_rerank: bool,
    use_filter: bool,
) -> tuple[bool, bool, bool, bool]:
    return (
        _env_flag("RAG_USE_HYBRID", use_hybrid),
        _env_flag("RAG_USE_MMR", use_mmr),
        _env_flag("RAG_USE_RERANK", use_rerank),
        _env_flag("RAG_USE_FILTER", use_filter),
    )


def _build_prompt(query_text: str, context: list[HybridHit]) -> str:
    joined = "\n\n".join(f"[chunk_id={h.chunk_id}] {h.chunk_text}" for h in context)
    return (
        "You are an assistant answering questions about Schedule C / expense "
        "deductions. Use ONLY the context below. Cite chunk_id values.\n\n"
        f"Context:\n{joined}\n\nQuestion: {query_text}"
    )


def _extract_answer_text(response: object) -> str:
    content = getattr(response, "content", None)
    if isinstance(content, list) and content:
        first = content[0]
        text = getattr(first, "text", None)
        if isinstance(text, str):
            return text
    if isinstance(content, str):
        return content
    return ""


@traceable(run_type="chain", name="expense_ai.retrieve_and_generate")
def retrieve_and_generate(
    query_text: str,
    tenant_id: str,
    *,
    anthropic: _AnthropicLike,
    conn: psycopg.Connection[psycopg.rows.TupleRow],
    r: redis.Redis,
    metadata_filter: Mapping[str, str] | None = None,
    model_name: str = "claude-sonnet-4-5",
    model_version: str = MODEL_NAME,
    embedder: _EncoderLike | None = None,
    use_hybrid: bool = True,
    use_mmr: bool = True,
    use_rerank: bool = True,
    use_filter: bool = True,
    dense_k: int = 50,
    sparse_k: int = 50,
    mmr_k: int = 20,
    top_k: int = 6,
) -> dict[str, object]:
    """End-to-end tenant-scoped RAG: cache -> retrieve -> fuse -> rerank -> LLM."""
    _require_langsmith_auth()
    flags_hybrid, flags_mmr, flags_rerank, flags_filter = _feature_flags(
        use_hybrid=use_hybrid,
        use_mmr=use_mmr,
        use_rerank=use_rerank,
        use_filter=use_filter,
    )
    active_filter = metadata_filter if flags_filter else None

    query_vec = _embed_query(query_text, embedder)

    cached = cache_lookup(r, query_vec, tenant_id)
    if cached is not None:
        return {**cached, "cache_hit": True}

    dense_hits = dense_topk_filtered(
        conn,
        query_vec=query_vec,
        tenant_id=tenant_id,
        metadata_filter=active_filter,
        k=dense_k,
        model_version=model_version,
    )

    if flags_hybrid:
        sparse_hits = sparse_topk_fts(
            conn,
            query_text=query_text,
            tenant_id=tenant_id,
            metadata_filter=active_filter,
            k=sparse_k,
            model_version=model_version,
        )
        fused = rrf_fuse(dense_hits, sparse_hits, k_const=60, top_k=60)
    else:
        fused = list(dense_hits)

    if flags_mmr and fused:
        diversified = mmr_pick(query_vec, fused, k=min(mmr_k, len(fused)))
    else:
        diversified = fused[:mmr_k]

    if flags_rerank and diversified:
        reranked, _timed_out = bge_rerank(
            query_text,
            diversified,
            top_k=top_k,
        )
        selected = reranked
    else:
        selected = diversified[:top_k]

    prompt = _build_prompt(query_text, selected)
    response = anthropic.messages.create(
        model=model_name,
        max_tokens=512,
        messages=[{"role": "user", "content": prompt}],
    )
    answer_text = _extract_answer_text(response)

    citations: list[dict[str, object]] = [
        {
            "chunk_id": h.chunk_id,
            "doc_id": h.doc_id,
            "tenant_id": h.tenant_id or tenant_id,
        }
        for h in selected
    ]
    result: dict[str, object] = {
        "answer": answer_text,
        "citations": citations,
        "cache_hit": False,
    }
    cache_store(r, query_vec, tenant_id, result)
    return result
