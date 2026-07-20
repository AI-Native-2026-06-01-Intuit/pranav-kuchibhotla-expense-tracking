"""Tests for W7D3 pgvector loader extensions (RagChunkRow, needs_embedding)."""

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
from expense_ai.pgvector_loader import (
    RagChunkRow,
    content_hash_for_text,
    load_rag_rows,
    needs_embedding,
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


def test_content_hash_is_stable() -> None:
    assert content_hash_for_text("hello") == content_hash_for_text("hello")
    assert content_hash_for_text("hello") != content_hash_for_text("hellox")


def test_load_rag_rows_stores_metadata_and_hash(pgvector_dsn: str) -> None:
    text = "IRS Schedule C line 22 supplies"
    row = RagChunkRow(
        doc_id="doc-A",
        chunk_idx=0,
        chunk_text=text,
        embedding=_emb(1),
        model_version=MODEL_NAME,
        tenant_id="tenant-a",
        chunk_metadata={"category": "schedule_c", "source": "irs"},
        content_hash=content_hash_for_text(text),
    )
    assert load_rag_rows(pgvector_dsn, [row]) == 1

    with psycopg.connect(pgvector_dsn) as conn, conn.cursor() as cur:
        cur.execute(
            "SELECT chunk_metadata, content_hash FROM doc_chunks "
            "WHERE doc_id = %s AND chunk_idx = %s",
            ("doc-A", 0),
        )
        got = cur.fetchone()
    assert got is not None
    meta, stored_hash = got
    assert meta == {"category": "schedule_c", "source": "irs"}
    assert stored_hash == content_hash_for_text(text)


def test_metadata_containment_filter(pgvector_dsn: str) -> None:
    rows = [
        RagChunkRow(
            doc_id=f"doc-{i}",
            chunk_idx=0,
            chunk_text=f"body {i}",
            embedding=_emb(i),
            model_version=MODEL_NAME,
            tenant_id="tenant-a",
            chunk_metadata={"category": "schedule_c" if i % 2 == 0 else "other"},
            content_hash=content_hash_for_text(f"body {i}"),
        )
        for i in range(6)
    ]
    load_rag_rows(pgvector_dsn, rows)

    with psycopg.connect(pgvector_dsn) as conn, conn.cursor() as cur:
        cur.execute(
            "SELECT count(*) FROM doc_chunks WHERE chunk_metadata @> %s::jsonb",
            ('{"category":"schedule_c"}',),
        )
        n = cur.fetchone()
    assert n is not None
    assert int(n[0]) == 3


def test_needs_embedding_gate(pgvector_dsn: str) -> None:
    text = "supplies deduction"
    h = content_hash_for_text(text)
    row = RagChunkRow(
        doc_id="doc-A",
        chunk_idx=0,
        chunk_text=text,
        embedding=_emb(1),
        model_version=MODEL_NAME,
        tenant_id="tenant-a",
        chunk_metadata={},
        content_hash=h,
    )
    load_rag_rows(pgvector_dsn, [row])

    with psycopg.connect(pgvector_dsn) as conn:
        # Unchanged content: no re-embedding needed.
        assert needs_embedding(conn, "doc-A", 0, MODEL_NAME, h) is False
        # Changed content: must re-embed.
        assert (
            needs_embedding(conn, "doc-A", 0, MODEL_NAME, content_hash_for_text("changed")) is True
        )
        # New chunk: must embed.
        assert needs_embedding(conn, "doc-B", 0, MODEL_NAME, h) is True
