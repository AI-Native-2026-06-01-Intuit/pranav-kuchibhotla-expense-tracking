"""Hybrid retrieval + RRF fusion tests against a Testcontainers pgvector DB."""

from __future__ import annotations

from collections.abc import Iterator

import numpy as np
import psycopg
import pytest
from _pg_wait import wait_for_postgres
from _schema import apply_all
from numpy.typing import NDArray
from testcontainers.postgres import PostgresContainer

from expense_ai.corpus import EMBEDDING_DIM, MODEL_NAME
from expense_ai.hybrid import (
    HybridHit,
    coverage,
    dense_topk_filtered,
    rrf_fuse,
    sparse_topk_fts,
)
from expense_ai.pgvector_loader import (
    RagChunkRow,
    content_hash_for_text,
    load_rag_rows,
)

pytestmark = pytest.mark.docker


def _emb(seed: int) -> NDArray[np.float32]:
    rng = np.random.default_rng(seed)
    vec = rng.standard_normal(EMBEDDING_DIM).astype(np.float32)
    norm = float(np.linalg.norm(vec)) or 1.0
    return (vec / norm).astype(np.float32)


@pytest.fixture(scope="module")
def pgvector_dsn() -> Iterator[str]:
    with PostgresContainer(
        "pgvector/pgvector:pg16",
        username="expense",
        password="expense",
        dbname="expense",
        driver=None,
    ) as pg:
        host = pg.get_container_host_ip()
        port = pg.get_exposed_port(5432)
        dsn = f"postgresql://expense:expense@{host}:{port}/expense"
        wait_for_postgres(dsn)
        apply_all(dsn)
        yield dsn


@pytest.fixture(autouse=True)
def _truncate(pgvector_dsn: str) -> Iterator[None]:
    with psycopg.connect(pgvector_dsn) as conn:
        with conn.cursor() as cur:
            cur.execute("TRUNCATE doc_chunks RESTART IDENTITY")
        conn.commit()
    yield


def _seed(dsn: str) -> None:
    rows = [
        RagChunkRow(
            doc_id="doc-sc-1",
            chunk_idx=0,
            chunk_text=(
                "Schedule C line 22 supplies deduction covers ordinary consumables "
                "used up during the tax year."
            ),
            embedding=_emb(1),
            model_version=MODEL_NAME,
            tenant_id="tenant-a",
            chunk_metadata={"category": "schedule_c"},
            content_hash=content_hash_for_text("sc1"),
        ),
        RagChunkRow(
            doc_id="doc-sc-2",
            chunk_idx=0,
            chunk_text=(
                "Home office pro-rata deduction requires exclusive and regular business use."
            ),
            embedding=_emb(2),
            model_version=MODEL_NAME,
            tenant_id="tenant-a",
            chunk_metadata={"category": "schedule_c"},
            content_hash=content_hash_for_text("sc2"),
        ),
        RagChunkRow(
            doc_id="doc-other-1",
            chunk_idx=0,
            chunk_text="Corporate tax rates are set by the Internal Revenue Code section 11.",
            embedding=_emb(3),
            model_version=MODEL_NAME,
            tenant_id="tenant-a",
            chunk_metadata={"category": "corporate"},
            content_hash=content_hash_for_text("o1"),
        ),
        RagChunkRow(
            doc_id="doc-b-1",
            chunk_idx=0,
            chunk_text="Tenant B private document about supplies deduction.",
            embedding=_emb(1),  # close to sc-1 vector
            model_version=MODEL_NAME,
            tenant_id="tenant-b",
            chunk_metadata={"category": "schedule_c"},
            content_hash=content_hash_for_text("b1"),
        ),
    ]
    load_rag_rows(dsn, rows)


def test_dense_topk_metadata_filter_returns_only_matching(pgvector_dsn: str) -> None:
    _seed(pgvector_dsn)
    with psycopg.connect(pgvector_dsn) as conn:
        hits = dense_topk_filtered(
            conn,
            query_vec=_emb(1),
            tenant_id="tenant-a",
            metadata_filter={"category": "schedule_c"},
            k=10,
        )
    assert hits
    for h in hits:
        assert h.tenant_id == "tenant-a"
        assert h.metadata.get("category") == "schedule_c"


def test_sparse_fts_finds_exact_phrase(pgvector_dsn: str) -> None:
    _seed(pgvector_dsn)
    with psycopg.connect(pgvector_dsn) as conn:
        hits = sparse_topk_fts(
            conn,
            query_text="supplies deduction",
            tenant_id="tenant-a",
            k=10,
        )
    assert hits
    # Top result should be one of the schedule_c docs containing "supplies deduction".
    assert hits[0].doc_id in {"doc-sc-1", "doc-sc-2", "doc-other-1"}
    ids = {h.doc_id for h in hits}
    assert "doc-sc-1" in ids


def test_rrf_fuse_returns_union_up_to_top_k() -> None:
    dense = [
        HybridHit(chunk_id=f"c-d{i}", doc_id=f"d{i}", chunk_idx=0, chunk_text="", score=1.0)
        for i in range(50)
    ]
    sparse = [
        HybridHit(chunk_id=f"c-s{i}", doc_id=f"s{i}", chunk_idx=0, chunk_text="", score=1.0)
        for i in range(50)
    ]
    fused = rrf_fuse(dense, sparse, k_const=60, top_k=60)
    assert len(fused) == 60
    fused_ids = {h.chunk_id for h in fused}
    # Top ranks of both lists should be represented.
    for i in range(5):
        assert f"c-d{i}" in fused_ids
        assert f"c-s{i}" in fused_ids


def test_rrf_fuse_accumulates_when_both_lists_agree() -> None:
    shared = HybridHit(chunk_id="c-x", doc_id="dx", chunk_idx=0, chunk_text="", score=1.0)
    d_only = HybridHit(chunk_id="c-d", doc_id="dd", chunk_idx=0, chunk_text="", score=1.0)
    s_only = HybridHit(chunk_id="c-s", doc_id="ds", chunk_idx=0, chunk_text="", score=1.0)
    fused = rrf_fuse([shared, d_only], [shared, s_only], k_const=60, top_k=10)
    top = fused[0]
    assert top.chunk_id == "c-x"


def test_coverage_jaccard_finite_in_unit_interval() -> None:
    dense = [
        HybridHit(chunk_id=f"c{i}", doc_id="d", chunk_idx=i, chunk_text="", score=1.0)
        for i in range(5)
    ]
    sparse = [
        HybridHit(chunk_id=f"c{i}", doc_id="d", chunk_idx=i, chunk_text="", score=1.0)
        for i in range(3, 8)
    ]
    cov = coverage(dense, sparse)
    assert 0.0 <= cov["jaccard"] <= 1.0
    assert cov["both"] == 2.0
    assert cov["dense_only"] == 3.0
    assert cov["sparse_only"] == 3.0


def test_coverage_empty_inputs() -> None:
    cov = coverage([], [])
    assert cov["jaccard"] == 0.0
