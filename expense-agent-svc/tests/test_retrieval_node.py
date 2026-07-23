"""Retrieval agent node contract.

Cover:

* Query rewrite preserves domain identifiers (``ord-*``, ``tenant-*``,
  digit runs).
* Empty / oversize rewrite falls back to the original question.
* The (possibly rewritten) query is what reaches the retriever.
* Tenant identifier is passed through untouched.
* Adapter drops bulky metadata and caps at ``TOP_DOCS`` = 8.
* Excerpt quote is bounded to ``MAX_QUOTE_CHARS`` = 240.
* Empty retrieval returns ``docs=[]``.
* Synchronous W7D3 callable runs on a worker thread (via injected
  ``to_thread`` shim).
* Deadline sentinel shape.
"""

from __future__ import annotations

import asyncio
from collections.abc import Callable, Mapping

import pytest

from expense_agent_svc.budgets import BudgetGuard
from expense_agent_svc.dependencies import (
    AgentDependencies,
    RequestContext,
    register_request,
    release_request,
)
from expense_agent_svc.nodes.retrieval import (
    MAX_QUOTE_CHARS,
    TOP_DOCS,
    make_retrieval_agent,
    retrieval_body_for_tests,
)
from expense_agent_svc.settings import Settings


class _StubClient:
    @property
    def messages(self) -> object:  # pragma: no cover
        return object()


class _FakeMCPSession:
    async def list_tools(self, cursor: str | None = None) -> object:  # pragma: no cover
        return object()

    async def call_tool(
        self,
        name: str,
        arguments: dict[str, object] | None = None,
    ) -> object:  # pragma: no cover
        return object()


def _make_deps(retrieve: Callable[[str, str], dict[str, object]]) -> AgentDependencies:
    return AgentDependencies(
        settings=Settings(),
        mcp_session=_FakeMCPSession(),
        anthropic=_StubClient(),
        instructor=_StubClient(),
        retrieve=retrieve,
    )


def _register_ctx() -> RequestContext:
    ctx = RequestContext(
        thread_id="thread-1",
        tenant_id="tenant-a",
        budget=BudgetGuard(),
    )
    register_request(ctx)
    return ctx


def _canned_retrieve(payload: dict[str, object]) -> Callable[[str, str], dict[str, object]]:
    calls: list[tuple[str, str]] = []

    def retrieve(query: str, tenant: str) -> dict[str, object]:
        calls.append((query, tenant))
        return payload

    retrieve.calls = calls  # type: ignore[attr-defined]
    return retrieve


async def _direct_to_thread(func: Callable[..., object], *args: object) -> object:
    """Skip the real threadpool but honour the async signature."""
    return func(*args)


@pytest.mark.asyncio
async def test_rewrite_preserves_identifiers() -> None:
    retrieve = _canned_retrieve(
        {
            "answer": "policy for ord-synth-9001",
            "citations": [{"chunk_id": "c1", "doc_id": "d1"}],
        }
    )
    deps = _make_deps(retrieve)
    ctx = _register_ctx()

    async def rewriter(q: str) -> str:
        return "please look up ord-synth-9001 for tenant-a"

    try:
        await retrieval_body_for_tests(
            {
                "question": "ord-synth-9001 tenant-a refund policy?",
                "tenant_id": "tenant-a",
                "thread_id": "thread-1",
                "request_id": ctx.request_id,
            },
            dependencies=deps,
            rewriter=rewriter,
            to_thread=_direct_to_thread,
        )
    finally:
        release_request(ctx.request_id)

    assert retrieve.calls, "retrieve was not called"  # type: ignore[attr-defined]
    query, tenant = retrieve.calls[0]  # type: ignore[attr-defined]
    assert "ord-synth-9001" in query
    assert "tenant-a" in query
    assert tenant == "tenant-a"


@pytest.mark.asyncio
async def test_rewrite_drops_identifier_falls_back_to_original() -> None:
    retrieve = _canned_retrieve({"answer": "", "citations": []})
    deps = _make_deps(retrieve)
    ctx = _register_ctx()

    async def rewriter(q: str) -> str:
        return "generic refund policy?"  # drops the ord id

    try:
        await retrieval_body_for_tests(
            {
                "question": "ord-synth-9001 tenant-a refund policy?",
                "tenant_id": "tenant-a",
                "thread_id": "thread-1",
                "request_id": ctx.request_id,
            },
            dependencies=deps,
            rewriter=rewriter,
            to_thread=_direct_to_thread,
        )
    finally:
        release_request(ctx.request_id)

    query, _tenant = retrieve.calls[0]  # type: ignore[attr-defined]
    assert query == "ord-synth-9001 tenant-a refund policy?"


@pytest.mark.asyncio
async def test_empty_rewrite_falls_back_to_original() -> None:
    retrieve = _canned_retrieve({"answer": "", "citations": []})
    deps = _make_deps(retrieve)
    ctx = _register_ctx()

    async def rewriter(q: str) -> str:
        return ""

    try:
        await retrieval_body_for_tests(
            {
                "question": "what qualifies as a home office deduction",
                "tenant_id": "tenant-a",
                "thread_id": "thread-1",
                "request_id": ctx.request_id,
            },
            dependencies=deps,
            rewriter=rewriter,
            to_thread=_direct_to_thread,
        )
    finally:
        release_request(ctx.request_id)

    query, _tenant = retrieve.calls[0]  # type: ignore[attr-defined]
    assert query == "what qualifies as a home office deduction"


@pytest.mark.asyncio
async def test_docs_capped_and_bounded() -> None:
    # Ten citations, big answer -> at most 8 docs, quote bounded to 240 chars.
    retrieve = _canned_retrieve(
        {
            "answer": "x" * 500,
            "citations": [
                {"chunk_id": f"c{i}", "doc_id": f"d{i}", "score": 0.1 * i, "extra": "junk"}
                for i in range(10)
            ],
        }
    )
    deps = _make_deps(retrieve)
    ctx = _register_ctx()

    try:
        result = await retrieval_body_for_tests(
            {
                "question": "policy?",
                "tenant_id": "tenant-a",
                "thread_id": "thread-1",
                "request_id": ctx.request_id,
            },
            dependencies=deps,
            to_thread=_direct_to_thread,
        )
    finally:
        release_request(ctx.request_id)

    docs = result["docs"]
    assert isinstance(docs, list)
    assert len(docs) == TOP_DOCS
    for doc in docs:
        assert "extra" not in doc, "bulky metadata leaked"
        assert set(doc.keys()) <= {"chunk_id", "doc_id", "score", "quote"}
        quote = doc.get("quote")
        assert isinstance(quote, str)
        assert len(quote) <= MAX_QUOTE_CHARS


@pytest.mark.asyncio
async def test_empty_retrieval_returns_empty_docs() -> None:
    retrieve = _canned_retrieve({"answer": "", "citations": []})
    deps = _make_deps(retrieve)
    ctx = _register_ctx()

    try:
        result = await retrieval_body_for_tests(
            {
                "question": "policy?",
                "tenant_id": "tenant-a",
                "thread_id": "thread-1",
                "request_id": ctx.request_id,
            },
            dependencies=deps,
            to_thread=_direct_to_thread,
        )
    finally:
        release_request(ctx.request_id)

    assert result["docs"] == []
    assert result["visited_nodes"] == ["retrieval_agent"]


@pytest.mark.asyncio
async def test_retrieval_error_yields_bounded_error_tag() -> None:
    def blowup(q: str, t: str) -> dict[str, object]:
        raise RuntimeError("pgvector down")

    deps = _make_deps(blowup)
    ctx = _register_ctx()
    try:
        result = await retrieval_body_for_tests(
            {
                "question": "policy?",
                "tenant_id": "tenant-a",
                "thread_id": "thread-1",
                "request_id": ctx.request_id,
            },
            dependencies=deps,
            to_thread=_direct_to_thread,
        )
    finally:
        release_request(ctx.request_id)

    errors = result["errors"]
    assert isinstance(errors, list)
    assert errors == ["retrieval_error:RuntimeError"]


@pytest.mark.asyncio
async def test_deadline_sentinel_shape() -> None:
    from expense_agent_svc.nodes._deadline import deadline

    async def slow(state: Mapping[str, object]) -> Mapping[str, object]:
        await asyncio.sleep(1.0)
        return {}

    sentinel: dict[str, object] = {
        "docs": [],
        "visited_nodes": ["retrieval_agent"],
        "errors": ["retrieval_deadline_exceeded"],
        "cost_usd_e5": 0,
    }
    wrapped = deadline(seconds=0.05, sentinel=sentinel)(slow)

    result = await wrapped({"question": "x"})
    assert result["errors"] == ["retrieval_deadline_exceeded"]
    assert result["visited_nodes"] == ["retrieval_agent"]
    assert result["deadline_exceeded"] is True


def test_make_retrieval_agent_returns_callable() -> None:
    retrieve = _canned_retrieve({"answer": "", "citations": []})
    deps = _make_deps(retrieve)
    node = make_retrieval_agent(deps)
    assert callable(node)
