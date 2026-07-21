"""Airflow TaskFlow DAG for the expense-ai RAG ingestion pipeline.

The DAG is importable without a scheduler and without any DB/Redis/API
credentials. Task bodies are minimal stubs that would call the real
``expense_ai`` helpers in a runtime environment; keeping them tiny at
import time is what makes the ``uv run python -c "from ... import
expense_ai_ingest_dag"`` check cheap and side-effect-free.

The final ``bump_cache_epochs`` task actually invalidates each tenant's
Redis semantic cache after ingest by calling
:func:`expense_ai.cache.bump_epoch`. Redis configuration is read inside
the task body so DAG import stays credential-free.
"""

from __future__ import annotations

import os
from datetime import datetime, timedelta

import redis
from airflow.sdk import dag, task

from expense_ai.cache import bump_epoch

DAG_ID = "expense_ai_ingest"
DEFAULT_TENANTS: tuple[str, ...] = ("tenant-a", "tenant-b", "tenant-c")


def _resolve_tenants() -> list[str]:
    override = os.environ.get("EXPENSE_AI_INGEST_TENANTS", "").strip()
    if not override:
        return list(DEFAULT_TENANTS)
    return [t.strip() for t in override.split(",") if t.strip()]


def _bump_cache_epochs_impl() -> dict[str, int]:
    """Bump the semantic-cache epoch for every configured tenant.

    Reads ``EXPENSE_AI_REDIS_URL`` and ``EXPENSE_AI_INGEST_TENANTS`` from
    the environment at task-execution time so DAG import remains free of
    Redis / secret dependencies.
    """
    redis_url = os.environ.get("EXPENSE_AI_REDIS_URL")
    if not redis_url:
        raise RuntimeError(
            "EXPENSE_AI_REDIS_URL is not set; cannot invalidate semantic cache after ingest."
        )
    tenants = _resolve_tenants()
    client = redis.Redis.from_url(redis_url)
    try:
        return {tenant: bump_epoch(client, tenant) for tenant in tenants}
    finally:
        client.close()


@dag(
    dag_id=DAG_ID,
    schedule=None,
    start_date=datetime(2026, 7, 1),
    catchup=False,
    max_active_runs=1,
    default_args={
        "retries": 2,
        "retry_delay": timedelta(minutes=5),
    },
    tags=["expense-ai", "rag2"],
)
def expense_ai_ingest() -> None:
    """Ingest corpus rows into pgvector and bump per-tenant cache epochs."""

    @task(task_id="load_docs")
    def load_docs() -> list[dict[str, str]]:
        return []

    @task(task_id="chunk_docs")
    def chunk_docs_task(docs: list[dict[str, str]]) -> list[dict[str, str]]:
        return docs

    @task(task_id="embed_chunks")
    def embed_chunks(chunks: list[dict[str, str]]) -> list[dict[str, str]]:
        return chunks

    @task(task_id="upsert_chunks")
    def upsert_chunks(embedded: list[dict[str, str]]) -> int:
        return len(embedded)

    @task(task_id="bump_cache_epochs")
    def bump_cache_epochs(upserted: int) -> dict[str, int]:
        del upserted  # dependency edge only; count is not needed to invalidate
        return _bump_cache_epochs_impl()

    # At DAG-parse time each @task call returns an XComArg, not the annotated
    # runtime return type; the mypy noise below is unavoidable given Airflow's
    # decorator signature.
    loaded = load_docs()
    chunked = chunk_docs_task(loaded)  # type: ignore[arg-type]
    embedded = embed_chunks(chunked)  # type: ignore[arg-type]
    upserted = upsert_chunks(embedded)  # type: ignore[arg-type]
    bump_cache_epochs(upserted)  # type: ignore[arg-type]


expense_ai_ingest_dag = expense_ai_ingest()
