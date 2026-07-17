"""Testcontainers-backed integration tests for the pgvector loader."""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

import numpy as np
import psycopg
import pytest
from _pg_wait import wait_for_postgres
from numpy.typing import NDArray
from pgvector.psycopg import register_vector
from testcontainers.postgres import PostgresContainer

from expense_ai.corpus import EMBEDDING_DIM, MODEL_NAME, CorpusRow
from expense_ai.pgvector_loader import load_rows

_SCHEMA_PATH = Path(__file__).resolve().parent.parent / "sql" / "V001__doc_chunks.sql"

pytestmark = pytest.mark.docker


def _deterministic_embedding(seed: int) -> NDArray[np.float32]:
    rng = np.random.default_rng(seed)
    vec = rng.standard_normal(EMBEDDING_DIM).astype(np.float32)
    norm = float(np.linalg.norm(vec))
    if norm == 0.0:
        norm = 1.0
    return (vec / norm).astype(np.float32)


def _make_rows(n: int, tenant: str = "tenant-a") -> list[CorpusRow]:
    return [
        CorpusRow(
            doc_id=f"merchant-{i:03d}",
            chunk_idx=0,
            chunk_text=f"chunk text {i}",
            embedding=_deterministic_embedding(i),
            model_version=MODEL_NAME,
            tenant_id=tenant,
        )
        for i in range(n)
    ]


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
        ddl = _SCHEMA_PATH.read_text()
        with psycopg.connect(dsn) as conn:
            with conn.cursor() as cur:
                cur.execute(ddl)
            conn.commit()
        yield dsn


@pytest.fixture(autouse=True)
def _truncate_doc_chunks(pgvector_dsn: str) -> Iterator[None]:
    with psycopg.connect(pgvector_dsn) as conn:
        with conn.cursor() as cur:
            cur.execute("TRUNCATE doc_chunks RESTART IDENTITY")
        conn.commit()
    yield


def _row_count(dsn: str) -> int:
    with psycopg.connect(dsn) as conn, conn.cursor() as cur:
        cur.execute("SELECT count(*) FROM doc_chunks")
        row = cur.fetchone()
        assert row is not None
        return int(row[0])


def test_load_rows_inserts_all(pgvector_dsn: str) -> None:
    rows = _make_rows(100)
    inserted = load_rows(pgvector_dsn, rows)
    assert inserted == 100
    assert _row_count(pgvector_dsn) == 100


def test_load_rows_is_idempotent(pgvector_dsn: str) -> None:
    rows = _make_rows(100)
    assert load_rows(pgvector_dsn, rows) == 100
    assert load_rows(pgvector_dsn, rows) == 100
    assert _row_count(pgvector_dsn) == 100


def test_load_rows_empty_returns_zero(pgvector_dsn: str) -> None:
    assert load_rows(pgvector_dsn, []) == 0
    assert _row_count(pgvector_dsn) == 0


def test_hnsw_index_present(pgvector_dsn: str) -> None:
    with psycopg.connect(pgvector_dsn) as conn, conn.cursor() as cur:
        cur.execute("SELECT indexname FROM pg_indexes WHERE tablename = 'doc_chunks'")
        indexes = {r[0] for r in cur.fetchall()}
    assert "doc_chunks_embedding_hnsw" in indexes


def test_ann_query_uses_hnsw_index(pgvector_dsn: str) -> None:
    rows = _make_rows(200)
    load_rows(pgvector_dsn, rows)
    query = _deterministic_embedding(0)
    with psycopg.connect(pgvector_dsn) as conn:
        register_vector(conn)
        with conn.cursor() as cur:
            cur.execute("ANALYZE doc_chunks")
            cur.execute("SET enable_seqscan = off")
            cur.execute(
                "EXPLAIN SELECT chunk_id FROM doc_chunks ORDER BY embedding <=> %s LIMIT 5",
                (query,),
            )
            plan = "\n".join(str(r[0]) for r in cur.fetchall())
    assert "doc_chunks_embedding_hnsw" in plan
    assert "Seq Scan" not in plan
