"""Unit tests for retrieve_and_generate against a Testcontainers pgvector + Redis stack."""

from __future__ import annotations

from collections.abc import Iterator

import numpy as np
import psycopg
import pytest
import redis
from _pg_wait import wait_for_postgres
from _schema import apply_all
from numpy.typing import NDArray
from testcontainers.postgres import PostgresContainer
from testcontainers.redis import RedisContainer

from expense_ai.corpus import EMBEDDING_DIM, MODEL_NAME
from expense_ai.pgvector_loader import (
    RagChunkRow,
    content_hash_for_text,
    load_rag_rows,
)
from expense_ai.rag import retrieve_and_generate

pytestmark = [pytest.mark.docker, pytest.mark.redis]


def _emb(seed: int) -> NDArray[np.float32]:
    rng = np.random.default_rng(seed)
    v = rng.standard_normal(EMBEDDING_DIM).astype(np.float32)
    n = float(np.linalg.norm(v)) or 1.0
    return (v / n).astype(np.float32)


class _FixedEncoder:
    def __init__(self, vec: NDArray[np.float32]) -> None:
        self._vec = vec

    def encode(
        self,
        sentences: list[str],
        batch_size: int = 64,
        normalize_embeddings: bool = True,
        convert_to_numpy: bool = True,
    ) -> NDArray[np.float32]:
        out = np.zeros((len(sentences), EMBEDDING_DIM), dtype=np.float32)
        for i, _ in enumerate(sentences):
            out[i] = self._vec
        return out


class _FakeMessages:
    def __init__(self, text: str) -> None:
        self._text = text
        self.calls = 0

    def create(
        self,
        *,
        model: str,
        max_tokens: int,
        messages: list[dict[str, str]],
    ) -> object:
        self.calls += 1

        class _Block:
            def __init__(self, text: str) -> None:
                self.text = text

        class _Resp:
            def __init__(self, text: str) -> None:
                self.content = [_Block(text)]

        return _Resp(self._text)


class _FakeAnthropic:
    def __init__(self, text: str) -> None:
        self.messages = _FakeMessages(text)


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


@pytest.fixture(scope="module")
def redis_client() -> Iterator[redis.Redis]:
    with RedisContainer("redis:7-alpine") as rc:
        host = rc.get_container_host_ip()
        port = int(rc.get_exposed_port(6379))
        client = redis.Redis(host=host, port=port, db=0)
        assert client.ping() is True
        yield client
        client.close()


@pytest.fixture(autouse=True)
def _clean(
    pgvector_dsn: str,
    redis_client: redis.Redis,
    monkeypatch: pytest.MonkeyPatch,
) -> Iterator[None]:
    with psycopg.connect(pgvector_dsn) as conn:
        with conn.cursor() as cur:
            cur.execute("TRUNCATE doc_chunks RESTART IDENTITY")
        conn.commit()
    redis_client.flushdb()
    monkeypatch.setenv("EXPENSE_AI_ALLOW_EXTERNAL_SKIP", "1")
    monkeypatch.delenv("LANGSMITH_API_KEY", raising=False)
    monkeypatch.setenv("LANGSMITH_TRACING", "false")
    for env in ("RAG_USE_HYBRID", "RAG_USE_MMR", "RAG_USE_RERANK", "RAG_USE_FILTER"):
        monkeypatch.delenv(env, raising=False)
    yield


def _seed_tenant_a(dsn: str, vec: NDArray[np.float32]) -> None:
    rows = [
        RagChunkRow(
            doc_id=f"doc-{i}",
            chunk_idx=0,
            chunk_text=f"Schedule C supplies deduction context {i}",
            embedding=vec if i < 3 else _emb(100 + i),
            model_version=MODEL_NAME,
            tenant_id="tenant-a",
            chunk_metadata={"category": "schedule_c"},
            content_hash=content_hash_for_text(f"body {i}"),
        )
        for i in range(6)
    ]
    load_rag_rows(dsn, rows)


def test_cache_hit_skips_anthropic(pgvector_dsn: str, redis_client: redis.Redis) -> None:
    q_vec = _emb(1)
    _seed_tenant_a(pgvector_dsn, q_vec)
    fake = _FakeAnthropic("first answer")

    with psycopg.connect(pgvector_dsn) as conn:
        out1 = retrieve_and_generate(
            "supplies deduction",
            tenant_id="tenant-a",
            anthropic=fake,
            conn=conn,
            r=redis_client,
            embedder=_FixedEncoder(q_vec),
            use_rerank=False,
        )
    assert out1["cache_hit"] is False
    assert fake.messages.calls == 1

    with psycopg.connect(pgvector_dsn) as conn:
        out2 = retrieve_and_generate(
            "supplies deduction",
            tenant_id="tenant-a",
            anthropic=fake,
            conn=conn,
            r=redis_client,
            embedder=_FixedEncoder(q_vec),
            use_rerank=False,
        )
    assert out2["cache_hit"] is True
    assert fake.messages.calls == 1  # unchanged: cache short-circuited


def test_citations_include_tenant_id(pgvector_dsn: str, redis_client: redis.Redis) -> None:
    q_vec = _emb(1)
    _seed_tenant_a(pgvector_dsn, q_vec)
    fake = _FakeAnthropic("ok")
    with psycopg.connect(pgvector_dsn) as conn:
        out = retrieve_and_generate(
            "supplies deduction",
            tenant_id="tenant-a",
            anthropic=fake,
            conn=conn,
            r=redis_client,
            embedder=_FixedEncoder(q_vec),
            use_rerank=False,
        )
    citations = out["citations"]
    assert isinstance(citations, list)
    assert citations, "expected at least one citation"
    for c in citations:
        assert isinstance(c, dict)
        assert c["tenant_id"] == "tenant-a"


def test_flags_disable_hybrid_and_rerank(pgvector_dsn: str, redis_client: redis.Redis) -> None:
    q_vec = _emb(1)
    _seed_tenant_a(pgvector_dsn, q_vec)
    fake = _FakeAnthropic("dense-only")
    with psycopg.connect(pgvector_dsn) as conn:
        out = retrieve_and_generate(
            "supplies deduction",
            tenant_id="tenant-a",
            anthropic=fake,
            conn=conn,
            r=redis_client,
            embedder=_FixedEncoder(q_vec),
            use_hybrid=False,
            use_mmr=False,
            use_rerank=False,
        )
    assert out["cache_hit"] is False
    assert fake.messages.calls == 1
