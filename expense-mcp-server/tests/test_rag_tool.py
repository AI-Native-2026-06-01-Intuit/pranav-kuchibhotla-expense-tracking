"""Unit tests for the RAG adapter: shape, top_k truncation, timeout, no internal leaks."""

import asyncio
from typing import Any

import pytest
from mcp import McpError

from expense_mcp_server.errors import CODE_RAG_TIMEOUT
from expense_mcp_server.tools.rag import _run_pipeline, _shape_answer
from expense_mcp_server.tools.schemas import RagArgs


def test_shape_answer_drops_internal_fields_and_truncates_top_k() -> None:
    raw = {
        "answer": "bounded",
        "cache_hit": False,
        "coverage": 0.9,
        "rerank_timed_out": False,
        "citations": [
            {"chunk_id": f"c-{i}", "doc_id": f"d-{i}", "score": 0.5 - i * 0.01, "extra": "leak"}
            for i in range(10)
        ],
    }
    shaped = _shape_answer(raw, top_k=3)
    assert shaped.answer == "bounded"
    assert len(shaped.citations) == 3
    # Extras are dropped by the strict schema.
    for c in shaped.citations:
        assert not hasattr(c, "extra")
    # The permissive raw ``cache_hit`` is not part of the DTO surface.
    assert not hasattr(shaped, "cache_hit")


def test_shape_answer_handles_missing_score_gracefully() -> None:
    raw = {
        "answer": "x",
        "citations": [{"chunk_id": "c-1", "doc_id": "d-1"}],
        "coverage": 0.0,
    }
    shaped = _shape_answer(raw, top_k=5)
    assert shaped.citations[0].score == 0.0


async def _slow_call(*_args: Any, **_kwargs: Any) -> dict[str, object]:
    await asyncio.sleep(2.0)
    return {"answer": "never"}


def _sync_slow(*_args: Any, **_kwargs: Any) -> dict[str, object]:
    import time

    time.sleep(2.0)
    return {"answer": "never"}


async def test_run_pipeline_maps_timeout_to_5040() -> None:
    args = RagArgs(question="is a laptop deductible?", tenant_id="tenant-a", top_k=3)
    with pytest.raises(McpError) as excinfo:
        await _run_pipeline(_sync_slow, args, timeout_s=0.05)
    assert excinfo.value.error.code == CODE_RAG_TIMEOUT


async def test_run_pipeline_success_calls_fake() -> None:
    calls = []

    def fake_rag(query: str, tenant: str, **kwargs: Any) -> dict[str, object]:
        calls.append((query, tenant, kwargs))
        return {"answer": "ok", "citations": [], "coverage": 1.0, "rerank_timed_out": False}

    args = RagArgs(question="is a laptop deductible?", tenant_id="tenant-a", top_k=3)
    raw = await _run_pipeline(fake_rag, args, timeout_s=5.0)
    assert raw["answer"] == "ok"
    assert calls[0][1] == "tenant-a"
    assert calls[0][2]["top_k"] == 3
