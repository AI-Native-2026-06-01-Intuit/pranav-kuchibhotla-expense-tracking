"""Hybrid dense + Postgres FTS retrieval with rank-based RRF fusion.

Dense recall (``dense_topk_filtered``) and sparse recall (``sparse_topk_fts``)
are both DB-side, tenant-filtered, and optionally metadata-filtered. Their
results are combined by Reciprocal Rank Fusion (``rrf_fuse``): a rank-based
scheme that does not require score normalization — a subtle but important
distinction called out in the W7D3 spec.

A ``coverage()`` diagnostic reports how much dense and sparse agree, which
is useful when triaging retrieval regressions.
"""

from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field

import numpy as np
import psycopg
from langsmith import traceable
from numpy.typing import NDArray
from pgvector.psycopg import register_vector

from .corpus import MODEL_NAME


@dataclass(frozen=True, slots=True)
class HybridHit:
    """One retrieved chunk in the hybrid pipeline.

    ``chunk_id`` is the stable identity used by RRF / MMR / caching.
    We derive it from ``(doc_id, chunk_idx, model_version)`` — the same
    identity key the loader upserts on — rather than the ``BIGSERIAL``
    surrogate ``chunk_id`` column, so it survives re-embed with a new model.
    """

    chunk_id: str
    doc_id: str
    chunk_idx: int
    chunk_text: str
    score: float
    tenant_id: str | None = None
    metadata: Mapping[str, str] = field(default_factory=dict)


def _stable_chunk_id(doc_id: str, chunk_idx: int, model_version: str) -> str:
    return f"{doc_id}:{chunk_idx}:{model_version}"


def _metadata_filter_arg(
    metadata_filter: Mapping[str, str] | None,
) -> str | None:
    if not metadata_filter:
        return None
    return json.dumps(dict(metadata_filter))


@traceable(run_type="retriever", name="expense_ai.dense_topk_filtered")
def dense_topk_filtered(
    conn: psycopg.Connection[psycopg.rows.TupleRow],
    query_vec: NDArray[np.float32],
    tenant_id: str,
    metadata_filter: Mapping[str, str] | None = None,
    k: int = 50,
    model_version: str = MODEL_NAME,
) -> list[HybridHit]:
    """Dense pgvector top-k with tenant + optional metadata containment filter."""
    register_vector(conn)
    filt = _metadata_filter_arg(metadata_filter)
    if filt is None:
        sql = (
            "SELECT doc_id, chunk_idx, chunk_text, chunk_metadata, tenant_id, "
            "embedding <=> %s AS distance "
            "FROM doc_chunks "
            "WHERE tenant_id = %s AND model_version = %s "
            "ORDER BY embedding <=> %s "
            "LIMIT %s"
        )
        params: tuple[object, ...] = (query_vec, tenant_id, model_version, query_vec, k)
    else:
        sql = (
            "SELECT doc_id, chunk_idx, chunk_text, chunk_metadata, tenant_id, "
            "embedding <=> %s AS distance "
            "FROM doc_chunks "
            "WHERE tenant_id = %s AND model_version = %s "
            "  AND chunk_metadata @> %s::jsonb "
            "ORDER BY embedding <=> %s "
            "LIMIT %s"
        )
        params = (query_vec, tenant_id, model_version, filt, query_vec, k)

    with conn.cursor() as cur:
        cur.execute(sql, params)
        rows = cur.fetchall()

    hits: list[HybridHit] = []
    for r in rows:
        doc_id = str(r[0])
        chunk_idx = int(r[1])
        chunk_text = str(r[2])
        raw_meta = r[3] or {}
        meta = {str(k2): str(v2) for k2, v2 in dict(raw_meta).items()}
        tenant = str(r[4])
        distance = float(r[5])
        hits.append(
            HybridHit(
                chunk_id=_stable_chunk_id(doc_id, chunk_idx, model_version),
                doc_id=doc_id,
                chunk_idx=chunk_idx,
                chunk_text=chunk_text,
                score=1.0 - distance,
                tenant_id=tenant,
                metadata=meta,
            )
        )
    return hits


@traceable(run_type="retriever", name="expense_ai.sparse_topk_fts")
def sparse_topk_fts(
    conn: psycopg.Connection[psycopg.rows.TupleRow],
    query_text: str,
    tenant_id: str,
    metadata_filter: Mapping[str, str] | None = None,
    k: int = 50,
    model_version: str = MODEL_NAME,
) -> list[HybridHit]:
    """Postgres FTS top-k with tenant + optional metadata containment filter."""
    filt = _metadata_filter_arg(metadata_filter)
    if filt is None:
        sql = (
            "SELECT doc_id, chunk_idx, chunk_text, chunk_metadata, tenant_id, "
            "ts_rank_cd(chunk_tsv, websearch_to_tsquery('english', %s)) AS score "
            "FROM doc_chunks "
            "WHERE tenant_id = %s AND model_version = %s "
            "  AND chunk_tsv @@ websearch_to_tsquery('english', %s) "
            "ORDER BY score DESC "
            "LIMIT %s"
        )
        params: tuple[object, ...] = (query_text, tenant_id, model_version, query_text, k)
    else:
        sql = (
            "SELECT doc_id, chunk_idx, chunk_text, chunk_metadata, tenant_id, "
            "ts_rank_cd(chunk_tsv, websearch_to_tsquery('english', %s)) AS score "
            "FROM doc_chunks "
            "WHERE tenant_id = %s AND model_version = %s "
            "  AND chunk_metadata @> %s::jsonb "
            "  AND chunk_tsv @@ websearch_to_tsquery('english', %s) "
            "ORDER BY score DESC "
            "LIMIT %s"
        )
        params = (query_text, tenant_id, model_version, filt, query_text, k)

    with conn.cursor() as cur:
        cur.execute(sql, params)
        rows = cur.fetchall()

    hits: list[HybridHit] = []
    for r in rows:
        doc_id = str(r[0])
        chunk_idx = int(r[1])
        chunk_text = str(r[2])
        raw_meta = r[3] or {}
        meta = {str(k2): str(v2) for k2, v2 in dict(raw_meta).items()}
        tenant = str(r[4])
        score = float(r[5])
        hits.append(
            HybridHit(
                chunk_id=_stable_chunk_id(doc_id, chunk_idx, model_version),
                doc_id=doc_id,
                chunk_idx=chunk_idx,
                chunk_text=chunk_text,
                score=score,
                tenant_id=tenant,
                metadata=meta,
            )
        )
    return hits


@traceable(run_type="chain", name="expense_ai.rrf_fuse")
def rrf_fuse(
    dense: Sequence[HybridHit],
    sparse: Sequence[HybridHit],
    k_const: int = 60,
    w_dense: float = 1.0,
    w_sparse: float = 1.0,
    top_k: int = 60,
) -> list[HybridHit]:
    """Reciprocal Rank Fusion. Rank-based only — no score normalization.

    For each list, contribute ``weight / (k_const + rank)`` where ``rank`` is
    1-based. If a chunk appears in both lists, contributions accumulate.
    """
    scores: dict[str, float] = {}
    hits_by_id: dict[str, HybridHit] = {}

    for rank, hit in enumerate(dense, start=1):
        scores[hit.chunk_id] = scores.get(hit.chunk_id, 0.0) + w_dense / (k_const + rank)
        hits_by_id.setdefault(hit.chunk_id, hit)

    for rank, hit in enumerate(sparse, start=1):
        scores[hit.chunk_id] = scores.get(hit.chunk_id, 0.0) + w_sparse / (k_const + rank)
        hits_by_id.setdefault(hit.chunk_id, hit)

    ordered = sorted(scores.items(), key=lambda kv: kv[1], reverse=True)
    fused: list[HybridHit] = []
    for chunk_id, fused_score in ordered[:top_k]:
        base = hits_by_id[chunk_id]
        fused.append(
            HybridHit(
                chunk_id=base.chunk_id,
                doc_id=base.doc_id,
                chunk_idx=base.chunk_idx,
                chunk_text=base.chunk_text,
                score=fused_score,
                tenant_id=base.tenant_id,
                metadata=base.metadata,
            )
        )
    return fused


def coverage(
    dense: Sequence[HybridHit],
    sparse: Sequence[HybridHit],
) -> dict[str, float]:
    """Diagnostic: how much do dense and sparse recall agree?

    Returns dense_only, sparse_only, both, and Jaccard overlap in [0, 1].
    """
    d_ids = {h.chunk_id for h in dense}
    s_ids = {h.chunk_id for h in sparse}
    inter = d_ids & s_ids
    union = d_ids | s_ids
    jac = len(inter) / len(union) if union else 0.0
    return {
        "dense_only": float(len(d_ids - s_ids)),
        "sparse_only": float(len(s_ids - d_ids)),
        "both": float(len(inter)),
        "jaccard": float(jac),
    }
