"""Non-Docker unit tests for pgvector_loader small helpers."""

from __future__ import annotations

import pytest

from expense_ai.pgvector_loader import dsn_from_env, load_rows


def test_load_rows_empty_returns_zero_without_connection() -> None:
    # An empty iterable must short-circuit before opening a connection,
    # so this must not require Postgres.
    assert load_rows("postgresql://invalid:invalid@localhost:1/none", []) == 0


def test_dsn_from_env_reads_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("EXPENSE_AI_PG_DSN", "postgresql://u:p@h:5432/d")
    assert dsn_from_env() == "postgresql://u:p@h:5432/d"


def test_dsn_from_env_missing_raises(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("EXPENSE_AI_PG_DSN", raising=False)
    with pytest.raises(RuntimeError, match="EXPENSE_AI_PG_DSN"):
        dsn_from_env()
