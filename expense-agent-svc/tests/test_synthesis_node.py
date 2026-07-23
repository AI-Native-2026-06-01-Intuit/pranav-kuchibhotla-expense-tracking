"""Synthesis agent contract.

Cover:

* :class:`Citation` and :class:`FinalAnswer` forbid extras and enforce
  the size/confidence bounds.
* Empty context (no docs, no tool_results) short-circuits to a refusal
  with confidence < 0.4 and empty citations, and the model is not
  called.
* Non-empty context invokes the Instructor client with
  ``response_model=FinalAnswer`` and ``max_retries=2``.
* Output is a JSON-serializable ``final_answer`` dump; the raw
  ``FinalAnswer`` pydantic object never leaks into state.
* Deadline sentinel shape matches the rubric.
"""

from __future__ import annotations

import asyncio
import json
from collections.abc import Callable, Mapping

import pytest
from pydantic import ValidationError

from expense_agent_svc.budgets import BudgetGuard
from expense_agent_svc.dependencies import (
    AgentDependencies,
    RequestContext,
    register_request,
    release_request,
)
from expense_agent_svc.nodes.synthesis import (
    Citation,
    FinalAnswer,
    make_synthesis_agent,
    synthesis_body_for_tests,
)
from expense_agent_svc.settings import Settings


class _FakeMCPSession:
    async def list_tools(self, cursor: str | None = None) -> object:  # pragma: no cover
        return object()

    async def call_tool(
        self,
        name: str,
        arguments: dict[str, object] | None = None,
    ) -> object:  # pragma: no cover
        return object()


def _stub_retrieve(query_text: str, tenant_id: str, /) -> dict[str, object]:
    del query_text, tenant_id
    return {"answer": "stub", "citations": []}


class _StubClient:
    @property
    def messages(self) -> object:  # pragma: no cover
        return object()


class _FakeInstructor:
    """Records the exact kwargs passed to messages.create()."""

    def __init__(self, canned: FinalAnswer) -> None:
        self._canned = canned
        self.calls: list[dict[str, object]] = []

    class _Messages:
        def __init__(self, parent: _FakeInstructor) -> None:
            self._parent = parent

        def create(
            self,
            *,
            response_model: type[FinalAnswer],
            messages: list[dict[str, object]],
            max_retries: int,
            model: str,
        ) -> FinalAnswer:
            self._parent.calls.append(
                {
                    "response_model": response_model,
                    "messages": messages,
                    "max_retries": max_retries,
                    "model": model,
                }
            )
            return self._parent._canned

    @property
    def messages(self) -> _FakeInstructor._Messages:
        return _FakeInstructor._Messages(self)


def _make_deps(
    instructor: _FakeInstructor | _StubClient,
) -> AgentDependencies:
    return AgentDependencies(
        settings=Settings(),
        mcp_session=_FakeMCPSession(),
        anthropic=_StubClient(),
        instructor=instructor,
        retrieve=_stub_retrieve,
    )


def _register_ctx() -> RequestContext:
    ctx = RequestContext(
        thread_id="thread-1",
        tenant_id="tenant-a",
        budget=BudgetGuard(),
    )
    register_request(ctx)
    return ctx


async def _direct_to_thread(func: Callable[..., FinalAnswer]) -> FinalAnswer:
    return func()


# ---------- Schema contract tests ----------


def test_citation_forbids_extras() -> None:
    with pytest.raises(ValidationError):
        Citation(doc_id="d1", quote="valid quote here", spice="nope")  # type: ignore[call-arg]


def test_citation_quote_length_bounds() -> None:
    with pytest.raises(ValidationError):
        Citation(doc_id="d1", quote="short")  # too short
    with pytest.raises(ValidationError):
        Citation(doc_id="d1", quote="q" * 300)  # too long


def test_final_answer_forbids_extras() -> None:
    with pytest.raises(ValidationError):
        FinalAnswer(  # type: ignore[call-arg]
            text="ok",
            citations=[],
            confidence=0.5,
            extra="nope",
        )


def test_final_answer_confidence_bounds() -> None:
    with pytest.raises(ValidationError):
        FinalAnswer(text="ok", citations=[], confidence=-0.1)
    with pytest.raises(ValidationError):
        FinalAnswer(text="ok", citations=[], confidence=1.1)


def test_final_answer_text_bounds() -> None:
    with pytest.raises(ValidationError):
        FinalAnswer(text="", citations=[], confidence=0.5)
    # Empty citations list is allowed for a refusal.
    FinalAnswer(text="ok", citations=[], confidence=0.5)


# ---------- Node behaviour tests ----------


@pytest.mark.asyncio
async def test_empty_context_refuses_without_invoking_model() -> None:
    fake = _FakeInstructor(
        canned=FinalAnswer(text="should not be used", citations=[], confidence=0.9)
    )
    deps = _make_deps(fake)
    ctx = _register_ctx()

    try:
        result = await synthesis_body_for_tests(
            {
                "question": "policy?",
                "tenant_id": "tenant-a",
                "thread_id": "thread-1",
                "request_id": ctx.request_id,
                "docs": [],
                "tool_results": {},
            },
            dependencies=deps,
            to_thread=_direct_to_thread,
        )
    finally:
        release_request(ctx.request_id)

    assert fake.calls == [], "empty context must not call the model"
    final = result["final_answer"]
    assert isinstance(final, dict)
    assert final["citations"] == []
    confidence = final["confidence"]
    assert isinstance(confidence, (int, float))
    assert confidence < 0.4


@pytest.mark.asyncio
async def test_nonempty_context_invokes_instructor_with_correct_kwargs() -> None:
    canned = FinalAnswer(
        text="Home office deductions are documented in policy 42.",
        citations=[Citation(doc_id="d1", quote="Home office is deductible when...")],
        confidence=0.85,
    )
    fake = _FakeInstructor(canned=canned)
    deps = _make_deps(fake)
    ctx = _register_ctx()

    try:
        result = await synthesis_body_for_tests(
            {
                "question": "Is home office deductible?",
                "tenant_id": "tenant-a",
                "thread_id": "thread-1",
                "request_id": ctx.request_id,
                "docs": [
                    {
                        "chunk_id": "c1",
                        "doc_id": "d1",
                        "quote": "Home office is deductible when...",
                    }
                ],
                "tool_results": {},
            },
            dependencies=deps,
            to_thread=_direct_to_thread,
        )
    finally:
        release_request(ctx.request_id)

    assert len(fake.calls) == 1
    call = fake.calls[0]
    assert call["response_model"] is FinalAnswer
    assert call["max_retries"] == 2
    assert isinstance(call["messages"], list)
    prompt = call["messages"][0]["content"]
    assert isinstance(prompt, str)
    assert "tenant-a" in prompt
    assert "Home office is deductible when..." in prompt

    # State-shape assertions.
    assert result["answer"] == canned.text
    dump = result["final_answer"]
    assert isinstance(dump, dict)
    # Must be JSON-serializable and free of pydantic-model objects.
    json.dumps(dump)


@pytest.mark.asyncio
async def test_no_pydantic_leak_in_state() -> None:
    canned = FinalAnswer(
        text="ok",
        citations=[Citation(doc_id="d1", quote="something something")],
        confidence=0.7,
    )
    fake = _FakeInstructor(canned=canned)
    deps = _make_deps(fake)
    ctx = _register_ctx()

    try:
        result = await synthesis_body_for_tests(
            {
                "question": "q?",
                "tenant_id": "tenant-a",
                "thread_id": "thread-1",
                "request_id": ctx.request_id,
                "docs": [{"doc_id": "d1", "chunk_id": "c1", "quote": "something something"}],
                "tool_results": {},
            },
            dependencies=deps,
            to_thread=_direct_to_thread,
        )
    finally:
        release_request(ctx.request_id)

    # None of the state values should be pydantic models.
    for value in result.values():
        assert not isinstance(value, (Citation, FinalAnswer))


@pytest.mark.asyncio
async def test_deadline_sentinel_shape() -> None:
    from expense_agent_svc.nodes._deadline import deadline

    async def slow(state: Mapping[str, object]) -> Mapping[str, object]:
        await asyncio.sleep(1.0)
        return {}

    sentinel: dict[str, object] = {
        "answer": "[deadline exceeded]",
        "final_answer": {"text": "[deadline exceeded]", "citations": [], "confidence": 0.0},
        "visited_nodes": ["synthesis_agent"],
        "errors": ["synthesis_deadline_exceeded"],
        "cost_usd_e5": 0,
    }
    wrapped = deadline(seconds=0.05, sentinel=sentinel)(slow)
    result = await wrapped({"question": "x"})
    assert result["errors"] == ["synthesis_deadline_exceeded"]
    assert result["visited_nodes"] == ["synthesis_agent"]
    assert result["answer"] == "[deadline exceeded]"


def test_make_synthesis_agent_returns_callable() -> None:
    fake = _FakeInstructor(canned=FinalAnswer(text="ok", citations=[], confidence=0.5))
    deps = _make_deps(fake)
    assert callable(make_synthesis_agent(deps))
