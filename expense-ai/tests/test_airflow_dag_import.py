"""Import-time check for the expense-ai ingestion DAG."""

from __future__ import annotations

import pytest


def test_dag_imports_without_scheduler() -> None:
    from expense_ai.dags.rag_svc_ingest import DAG_ID, expense_ai_ingest_dag

    assert expense_ai_ingest_dag.dag_id == DAG_ID
    assert expense_ai_ingest_dag.max_active_runs == 1

    task_ids = {t.task_id for t in expense_ai_ingest_dag.tasks}
    assert task_ids == {
        "load_docs",
        "chunk_docs",
        "embed_chunks",
        "upsert_chunks",
        "bump_cache_epochs",
    }


def test_dag_retry_config() -> None:
    from datetime import timedelta

    from expense_ai.dags.rag_svc_ingest import expense_ai_ingest_dag

    for task in expense_ai_ingest_dag.tasks:
        assert task.retries == 2
        assert task.retry_delay == timedelta(minutes=5)


def test_bump_cache_epochs_defaults_to_three_tenants(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from expense_ai.dags import rag_svc_ingest

    monkeypatch.setenv("EXPENSE_AI_REDIS_URL", "redis://unused-in-test:6379/0")
    monkeypatch.delenv("EXPENSE_AI_INGEST_TENANTS", raising=False)

    class _StubClient:
        def close(self) -> None:
            return None

    stub = _StubClient()

    class _FakeRedisClass:
        @staticmethod
        def from_url(url: str) -> object:
            assert url == "redis://unused-in-test:6379/0"
            return stub

    class _FakeRedisModule:
        Redis = _FakeRedisClass

    monkeypatch.setattr(rag_svc_ingest, "redis", _FakeRedisModule)

    calls: list[tuple[object, str]] = []
    counter = {"n": 0}

    def _fake_bump(client: object, tenant: str) -> int:
        calls.append((client, tenant))
        counter["n"] += 1
        return counter["n"]

    monkeypatch.setattr(rag_svc_ingest, "bump_epoch", _fake_bump)

    result = rag_svc_ingest._bump_cache_epochs_impl()

    assert result == {"tenant-a": 1, "tenant-b": 2, "tenant-c": 3}
    assert [t for _, t in calls] == ["tenant-a", "tenant-b", "tenant-c"]
    assert all(c is stub for c, _ in calls)


def test_bump_cache_epochs_honors_env_override(monkeypatch: pytest.MonkeyPatch) -> None:
    from expense_ai.dags import rag_svc_ingest

    monkeypatch.setenv("EXPENSE_AI_REDIS_URL", "redis://x:6379/0")
    monkeypatch.setenv("EXPENSE_AI_INGEST_TENANTS", "tenant-x , tenant-y ,, tenant-z")

    class _StubClient:
        def close(self) -> None:
            return None

    stub = _StubClient()

    class _FakeRedisClass:
        @staticmethod
        def from_url(url: str) -> object:
            return stub

    class _FakeRedisModule:
        Redis = _FakeRedisClass

    monkeypatch.setattr(rag_svc_ingest, "redis", _FakeRedisModule)

    seen: list[str] = []

    def _fake_bump(_client: object, tenant: str) -> int:
        seen.append(tenant)
        return 42

    monkeypatch.setattr(rag_svc_ingest, "bump_epoch", _fake_bump)

    result = rag_svc_ingest._bump_cache_epochs_impl()

    assert seen == ["tenant-x", "tenant-y", "tenant-z"]
    assert result == {"tenant-x": 42, "tenant-y": 42, "tenant-z": 42}


def test_bump_cache_epochs_requires_redis_url(monkeypatch: pytest.MonkeyPatch) -> None:
    from expense_ai.dags import rag_svc_ingest

    monkeypatch.delenv("EXPENSE_AI_REDIS_URL", raising=False)
    with pytest.raises(RuntimeError, match="EXPENSE_AI_REDIS_URL"):
        rag_svc_ingest._bump_cache_epochs_impl()
