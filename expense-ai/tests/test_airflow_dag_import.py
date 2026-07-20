"""Import-time check for the expense-ai ingestion DAG."""

from __future__ import annotations


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
