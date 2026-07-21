"""DB-side tenant isolation tests: never trust the request parameter alone.

For each returned chunk, we verify tenant_id at the SQL level by looking up
the row directly in ``doc_chunks``. This catches accidental joins,
misfiltered indexes, or SQL that drops the tenant predicate.
"""

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
from expense_ai.hybrid import dense_topk_filtered, sparse_topk_fts
from expense_ai.pgvector_loader import (
    RagChunkRow,
    content_hash_for_text,
    load_rag_rows,
)

pytestmark = pytest.mark.docker


def _emb(seed: int) -> NDArray[np.float32]:
    rng = np.random.default_rng(seed)
    v = rng.standard_normal(EMBEDDING_DIM).astype(np.float32)
    n = float(np.linalg.norm(v)) or 1.0
    return (v / n).astype(np.float32)


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


def _seed_three_tenants(dsn: str) -> None:
    """Seed each tenant with similar-content rows so retrieval could confuse them."""
    shared_text = "Schedule C supplies deduction line 22 explanation"
    rows: list[RagChunkRow] = []
    for t_idx, tenant in enumerate(("tenant-a", "tenant-b", "tenant-c")):
        for i in range(5):
            rows.append(
                RagChunkRow(
                    doc_id=f"{tenant}-doc-{i}",
                    chunk_idx=0,
                    chunk_text=f"{shared_text} ({tenant} row {i})",
                    embedding=_emb((t_idx + 1) * 100 + i),
                    model_version=MODEL_NAME,
                    tenant_id=tenant,
                    chunk_metadata={"category": "schedule_c"},
                    content_hash=content_hash_for_text(f"{tenant}-{i}"),
                )
            )
    load_rag_rows(dsn, rows)


def _verify_tenant_db_side(dsn: str, doc_ids: list[str], expected_tenant: str) -> None:
    with psycopg.connect(dsn) as conn, conn.cursor() as cur:
        cur.execute(
            "SELECT doc_id, tenant_id FROM doc_chunks WHERE doc_id = ANY(%s)",
            (doc_ids,),
        )
        rows = cur.fetchall()
    assert rows, f"no rows found for doc_ids {doc_ids}"
    for doc_id, tenant in rows:
        assert tenant == expected_tenant, f"doc {doc_id} belongs to {tenant}, not {expected_tenant}"


def test_dense_isolation_verified_db_side(pgvector_dsn: str) -> None:
    _seed_three_tenants(pgvector_dsn)
    with psycopg.connect(pgvector_dsn) as conn:
        hits = dense_topk_filtered(
            conn,
            query_vec=_emb(101),  # near tenant-a seeds
            tenant_id="tenant-a",
            k=15,
        )
    assert hits, "expected at least one dense hit for tenant-a"
    for h in hits:
        assert h.tenant_id == "tenant-a"
    _verify_tenant_db_side(pgvector_dsn, [h.doc_id for h in hits], expected_tenant="tenant-a")


def test_sparse_isolation_verified_db_side(pgvector_dsn: str) -> None:
    _seed_three_tenants(pgvector_dsn)
    with psycopg.connect(pgvector_dsn) as conn:
        hits = sparse_topk_fts(
            conn,
            query_text="supplies deduction line 22",
            tenant_id="tenant-b",
            k=15,
        )
    assert hits, "expected at least one FTS hit for tenant-b"
    for h in hits:
        assert h.tenant_id == "tenant-b"
    _verify_tenant_db_side(pgvector_dsn, [h.doc_id for h in hits], expected_tenant="tenant-b")


def test_tenant_c_metadata_filter_still_isolates(pgvector_dsn: str) -> None:
    _seed_three_tenants(pgvector_dsn)
    with psycopg.connect(pgvector_dsn) as conn:
        hits = dense_topk_filtered(
            conn,
            query_vec=_emb(301),
            tenant_id="tenant-c",
            metadata_filter={"category": "schedule_c"},
            k=15,
        )
    assert hits
    for h in hits:
        assert h.tenant_id == "tenant-c"
    _verify_tenant_db_side(pgvector_dsn, [h.doc_id for h in hits], expected_tenant="tenant-c")
