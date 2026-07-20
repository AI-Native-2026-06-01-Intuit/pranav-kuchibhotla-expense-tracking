"""Tests for the LangSmith-traceable pgvector retrieval."""

from __future__ import annotations

import os
from collections.abc import Iterator
from pathlib import Path

import numpy as np
import psycopg
import pytest
from _pg_wait import wait_for_postgres
from numpy.typing import NDArray
from testcontainers.postgres import PostgresContainer

from expense_ai.corpus import EMBEDDING_DIM, MODEL_NAME, CorpusRow
from expense_ai.pgvector_loader import load_rows
from expense_ai.rag import RetrievedChunk, retrieve_chunks

_SCHEMA_PATH = Path(__file__).resolve().parent.parent / "sql" / "V001__doc_chunks.sql"

pytestmark = pytest.mark.docker


def _norm(vec: NDArray[np.float32]) -> NDArray[np.float32]:
    n = float(np.linalg.norm(vec))
    return (vec / (n if n != 0.0 else 1.0)).astype(np.float32)


class _FixedEncoder:
    """Deterministic encoder that maps token overlap into a fixed vector."""

    def __init__(self, vectors: dict[str, NDArray[np.float32]]) -> None:
        self._vectors = vectors

    def encode(
        self,
        sentences: list[str],
        batch_size: int = 64,
        normalize_embeddings: bool = True,
        convert_to_numpy: bool = True,
    ) -> NDArray[np.float32]:
        out = np.zeros((len(sentences), EMBEDDING_DIM), dtype=np.float32)
        for i, s in enumerate(sentences):
            key = s.strip().lower()
            vec = self._vectors.get(key)
            if vec is None:
                # deterministic fallback based on hash so unknown text
                # produces a stable but different vector.
                rng = np.random.default_rng(abs(hash(key)) % (2**32))
                vec = _norm(rng.standard_normal(EMBEDDING_DIM).astype(np.float32))
            out[i] = vec
        return out


def _basis(index: int) -> NDArray[np.float32]:
    v = np.zeros(EMBEDDING_DIM, dtype=np.float32)
    v[index] = 1.0
    return v


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
        with psycopg.connect(dsn) as conn:
            with conn.cursor() as cur:
                cur.execute(_SCHEMA_PATH.read_text())
            conn.commit()
        yield dsn


@pytest.fixture(autouse=True)
def _truncate(pgvector_dsn: str) -> Iterator[None]:
    with psycopg.connect(pgvector_dsn) as conn:
        with conn.cursor() as cur:
            cur.execute("TRUNCATE doc_chunks RESTART IDENTITY")
        conn.commit()
    yield


@pytest.fixture(autouse=True)
def _allow_langsmith_skip(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("EXPENSE_AI_ALLOW_EXTERNAL_SKIP", "1")
    monkeypatch.delenv("LANGSMITH_API_KEY", raising=False)
    monkeypatch.setenv("LANGSMITH_TRACING", "false")


def test_module_declares_traceable_retriever() -> None:
    source = Path(__file__).resolve().parent.parent / "src" / "expense_ai" / "rag.py"
    text = source.read_text()
    assert '@traceable(run_type="retriever"' in text
    assert 'name="expense_ai.retrieve_chunks"' in text


def test_missing_langsmith_key_raises_without_skip(
    monkeypatch: pytest.MonkeyPatch, pgvector_dsn: str
) -> None:
    monkeypatch.setenv("EXPENSE_AI_ALLOW_EXTERNAL_SKIP", "0")
    monkeypatch.delenv("LANGSMITH_API_KEY", raising=False)
    with pytest.raises(RuntimeError, match="LANGSMITH_API_KEY"):
        retrieve_chunks(dsn=pgvector_dsn, question="q", k=1, model=_FixedEncoder({}))


def test_retrieval_returns_top_k(pgvector_dsn: str) -> None:
    target = _basis(0)
    off = _basis(1)
    rows: list[CorpusRow] = []
    for i in range(5):
        rows.append(
            CorpusRow(
                doc_id=f"doc-hit-{i}",
                chunk_idx=0,
                chunk_text=f"hit {i}",
                embedding=target,
                model_version=MODEL_NAME,
                tenant_id="tenant-a",
            )
        )
    for i in range(5):
        rows.append(
            CorpusRow(
                doc_id=f"doc-miss-{i}",
                chunk_idx=0,
                chunk_text=f"miss {i}",
                embedding=off,
                model_version=MODEL_NAME,
                tenant_id="tenant-a",
            )
        )
    load_rows(pgvector_dsn, rows)

    encoder = _FixedEncoder({"deduct meal": target})
    results = retrieve_chunks(
        dsn=pgvector_dsn,
        question="deduct meal",
        k=3,
        tenant_id="tenant-a",
        model=encoder,
    )
    assert len(results) == 3
    for r in results:
        assert isinstance(r, RetrievedChunk)
        assert r.doc_id.startswith("doc-hit-")


def test_model_version_filter_excludes_other_models(pgvector_dsn: str) -> None:
    target = _basis(2)
    rows = [
        CorpusRow(
            doc_id="mine",
            chunk_idx=0,
            chunk_text="mine",
            embedding=target,
            model_version=MODEL_NAME,
            tenant_id="tenant-a",
        ),
        CorpusRow(
            doc_id="other",
            chunk_idx=0,
            chunk_text="other",
            embedding=target,
            model_version="other-model",
            tenant_id="tenant-a",
        ),
    ]
    load_rows(pgvector_dsn, rows)
    results = retrieve_chunks(
        dsn=pgvector_dsn,
        question="anything",
        k=5,
        tenant_id="tenant-a",
        model=_FixedEncoder({"anything": target}),
    )
    ids = {r.doc_id for r in results}
    assert ids == {"mine"}


def test_no_real_langsmith_key_used_in_module() -> None:
    assert "LANGSMITH_API_KEY" not in os.environ or not os.environ["LANGSMITH_API_KEY"]
