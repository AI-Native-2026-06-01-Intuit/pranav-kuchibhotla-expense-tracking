"""Synthesis agent node.

Uses the injected Instructor-compatible client to produce a
:class:`FinalAnswer` grounded in the docs + tool_results the two worker
branches produced. When both branches are empty we short-circuit to a
deterministic refusal without invoking the model — this keeps the
refusal path deterministic and prevents wasted spend when the graph
has nothing to ground on.

The Instructor client is a Protocol (see
:class:`~expense_agent_svc.dependencies.InstructorClientLike`); the
real client is constructed by the FastAPI lifespan in Phase 14 and
never at module import time.
"""

from __future__ import annotations

import json
from collections.abc import Awaitable, Callable, Mapping
from typing import Any, Protocol

from langsmith import traceable
from pydantic import BaseModel, ConfigDict, Field

from ..budgets import BudgetExceeded
from ..dependencies import AgentDependencies, get_request_context_for_state
from ._deadline import deadline

SYNTHESIS_DEADLINE_SECONDS = 8.0
MAX_DOCS_IN_PROMPT = 8
MAX_TOOL_RESULTS_IN_PROMPT = 4
MAX_DOC_QUOTE_CHARS = 240
MAX_TOOL_TEXT_CHARS = 400

_TIMEOUT_SENTINEL: dict[str, object] = {
    "answer": "[deadline exceeded]",
    "final_answer": {
        "text": "[deadline exceeded]",
        "citations": [],
        "confidence": 0.0,
    },
    "visited_nodes": ["synthesis_agent"],
    "errors": ["synthesis_deadline_exceeded"],
    "cost_usd_e5": 0,
}


class Citation(BaseModel):
    """One grounded citation for a :class:`FinalAnswer`."""

    model_config = ConfigDict(extra="forbid")

    doc_id: str
    quote: str = Field(min_length=10, max_length=240)


class FinalAnswer(BaseModel):
    """Typed synthesis output.

    ``confidence`` is a bounded probability, not money, so ``float`` is
    the natural type here (see the domain rule: floats are forbidden
    only for monetary values).
    """

    model_config = ConfigDict(extra="forbid")

    text: str = Field(min_length=1, max_length=2000)
    citations: list[Citation]
    confidence: float = Field(ge=0.0, le=1.0)


def _refusal() -> FinalAnswer:
    return FinalAnswer(
        text=(
            "I do not have grounded context to answer this question. "
            "Please provide relevant documentation or an order id."
        ),
        citations=[],
        confidence=0.2,
    )


def _bounded_docs_for_prompt(docs: list[dict[str, object]]) -> list[dict[str, object]]:
    out: list[dict[str, object]] = []
    for d in docs[:MAX_DOCS_IN_PROMPT]:
        if not isinstance(d, Mapping):
            continue
        entry: dict[str, object] = {}
        for key in ("chunk_id", "doc_id"):
            v = d.get(key)
            if isinstance(v, str):
                entry[key] = v
        quote = d.get("quote")
        if isinstance(quote, str):
            entry["quote"] = quote[:MAX_DOC_QUOTE_CHARS]
        if entry:
            out.append(entry)
    return out


def _bounded_tool_results_for_prompt(
    tool_results: Mapping[str, object],
) -> dict[str, str]:
    out: dict[str, str] = {}
    for i, (name, payload) in enumerate(tool_results.items()):
        if i >= MAX_TOOL_RESULTS_IN_PROMPT:
            break
        out[name] = str(payload)[:MAX_TOOL_TEXT_CHARS]
    return out


def _build_prompt(
    *,
    tenant_id: str,
    question: str,
    docs: list[dict[str, object]],
    tool_results: Mapping[str, object],
) -> str:
    docs_json = json.dumps(_bounded_docs_for_prompt(docs))
    tools_json = json.dumps(_bounded_tool_results_for_prompt(tool_results))
    return (
        f"You are answering for tenant {tenant_id}. "
        "Use only the docs and tool_results provided below. "
        "Never fabricate citations; every citation.doc_id must appear "
        "in docs.doc_id and every citation.quote must be a substring of "
        "the corresponding doc quote or tool result. If neither source "
        "supports the question, refuse and set confidence < 0.4 and "
        "citations to []."
        f"\n\nquestion: {question}"
        f"\n\ndocs: {docs_json}"
        f"\n\ntool_results: {tools_json}"
    )


# The Instructor client contract we actually call. Kept as a small
# Protocol so tests do not need to import instructor.
class _InstructorMessagesLike(Protocol):
    def create(
        self,
        *,
        response_model: type[FinalAnswer],
        messages: list[dict[str, object]],
        max_retries: int,
        model: str,
    ) -> FinalAnswer: ...


class _InstructorClientLike(Protocol):
    @property
    def messages(self) -> _InstructorMessagesLike: ...


CostRecorder = Callable[[object, FinalAnswer], int]


def _default_cost_recorder(budget: object, final: FinalAnswer) -> int:
    del budget, final
    return 0


# Optional async factory: when the injected Instructor client exposes
# ``messages.create_with_completion`` we use it so we can capture the
# raw Anthropic completion's ``usage`` and feed real integer token
# counts into ``BudgetGuard.record_usage``. When the fake client under
# test only exposes ``create``, we fall back to the original path.
UsageAwareSynthesizer = Callable[
    [Any, str, str, str, int],
    Awaitable[tuple[FinalAnswer, int]],
]


async def _synthesis_body(
    state: Mapping[str, object],
    *,
    dependencies: AgentDependencies,
    cost_recorder: CostRecorder = _default_cost_recorder,
    to_thread: Callable[..., Awaitable[FinalAnswer]] | None = None,
    synthesizer: UsageAwareSynthesizer | None = None,
) -> Mapping[str, object]:
    ctx = get_request_context_for_state(state)

    docs_raw = state.get("docs") or []
    docs: list[dict[str, object]] = list(docs_raw) if isinstance(docs_raw, list) else []
    tool_results_raw = state.get("tool_results") or {}
    tool_results: dict[str, object] = (
        dict(tool_results_raw) if isinstance(tool_results_raw, Mapping) else {}
    )

    # Deterministic refusal when neither branch has grounded content.
    if not docs and not tool_results:
        refusal = _refusal()
        return {
            "answer": refusal.text,
            "final_answer": refusal.model_dump(mode="json"),
            "cost_usd_e5": 0,
            "visited_nodes": ["synthesis_agent"],
            "errors": [],
        }

    try:
        ctx.budget.check_or_raise()
    except BudgetExceeded:
        refusal = _refusal()
        return {
            "answer": refusal.text,
            "final_answer": refusal.model_dump(mode="json"),
            "cost_usd_e5": 0,
            "visited_nodes": ["synthesis_agent"],
            "errors": ["budget_exceeded"],
        }

    prompt = _build_prompt(
        tenant_id=str(state.get("tenant_id", ctx.tenant_id)),
        question=str(state.get("question", "")),
        docs=docs,
        tool_results=tool_results,
    )

    # Two paths:
    #
    # * Production wires ``synthesizer`` (see :func:`make_synthesis_agent`
    #   in Phase 15) to Instructor's async
    #   ``messages.create_with_completion``. That path returns the
    #   parsed :class:`FinalAnswer` **and** the raw Anthropic completion
    #   so we can pull real ``usage`` and hand integer token counts to
    #   :class:`BudgetGuard.record_usage`.
    # * Tests inject a synchronous fake through the legacy
    #   ``client.messages.create`` path plus a ``cost_recorder`` hook.
    client = dependencies.instructor
    if not hasattr(client, "messages"):
        raise TypeError("dependencies.instructor lacks a 'messages' attribute")

    if synthesizer is not None:
        final, delta_cost = await synthesizer(
            ctx.budget,
            prompt,
            dependencies.settings.model_name,
            "user",
            2,  # max_retries — kept explicit at the call site
        )
    else:

        def _invoke() -> FinalAnswer:
            response: FinalAnswer = client.messages.create(  # type: ignore[attr-defined]
                response_model=FinalAnswer,
                max_retries=2,
                model=dependencies.settings.model_name,
                messages=[{"role": "user", "content": prompt}],
            )
            return response

        import asyncio as _asyncio

        runner = to_thread if to_thread is not None else _asyncio.to_thread
        final = await runner(_invoke)
        delta_cost = cost_recorder(ctx.budget, final)

    return {
        "answer": final.text,
        "final_answer": final.model_dump(mode="json"),
        "cost_usd_e5": delta_cost,
        "visited_nodes": ["synthesis_agent"],
        "errors": [],
    }


def _make_default_synthesizer(
    input_rate_usd_e5_per_million: int,
    output_rate_usd_e5_per_million: int,
) -> UsageAwareSynthesizer:
    """Return a production synthesizer that captures real Instructor usage.

    The bound closure calls the async ``AsyncInstructor.messages.
    create_with_completion`` API — the SDK returns
    ``(parsed_model, raw_completion)`` so we can pull real
    ``raw_completion.usage.input_tokens`` and ``.output_tokens`` and
    feed them into :meth:`BudgetGuard.record_usage`. Missing usage
    counts as zero cost (we never invent tokens).
    """

    async def synthesizer(
        client: Any,
        prompt: str,
        model_name: str,
        role: str,
        max_retries: int,
    ) -> tuple[FinalAnswer, int]:
        del role
        parsed, raw = await client.messages.create_with_completion(
            model=model_name,
            max_tokens=1024,
            messages=[{"role": "user", "content": prompt}],
            response_model=FinalAnswer,
            max_retries=max_retries,
        )
        usage = getattr(raw, "usage", None)
        if usage is None:
            return parsed, 0
        input_tokens = int(getattr(usage, "input_tokens", 0) or 0)
        output_tokens = int(getattr(usage, "output_tokens", 0) or 0)
        # ``client`` here is the injected budget (see how
        # ``_synthesis_body`` forwards ``ctx.budget`` as the first arg
        # to the synthesizer). The awkward reuse of the parameter
        # ``client`` keeps the Callable signature narrow.
        return parsed, (
            input_tokens * input_rate_usd_e5_per_million // 1_000_000
            + output_tokens * output_rate_usd_e5_per_million // 1_000_000
        )

    return synthesizer


def make_synthesis_agent(
    dependencies: AgentDependencies,
    *,
    cost_recorder: CostRecorder = _default_cost_recorder,
    synthesizer: UsageAwareSynthesizer | None = None,
) -> Callable[[Mapping[str, object]], Awaitable[Mapping[str, object]]]:
    """Return the deadline-wrapped async synthesis node.

    ``synthesizer`` — when injected, replaces the fake-friendly
    ``client.messages.create`` path. Production wires it via
    :func:`_make_default_synthesizer` so real usage is recorded on the
    request's ``BudgetGuard``.
    """
    if synthesizer is None:
        # Only enable the production synthesizer when the injected
        # instructor client actually exposes ``create_with_completion``
        # — the test fakes do not, and we do not want to force them to.
        maybe_messages = getattr(dependencies.instructor, "messages", None)
        if maybe_messages is not None and hasattr(maybe_messages, "create_with_completion"):
            synthesizer = _bind_default_synthesizer(dependencies)

    @deadline(seconds=SYNTHESIS_DEADLINE_SECONDS, sentinel=_TIMEOUT_SENTINEL)
    @traceable(name="synthesis_agent", project_name="expense-agent-svc-dev")
    async def synthesis_agent(state: Mapping[str, object]) -> Mapping[str, object]:
        return await _synthesis_body(
            state,
            dependencies=dependencies,
            cost_recorder=cost_recorder,
            synthesizer=synthesizer,
        )

    return synthesis_agent


def _bind_default_synthesizer(
    dependencies: AgentDependencies,
) -> UsageAwareSynthesizer:
    """Bind the production synthesizer to the injected Instructor client."""
    base = _make_default_synthesizer(
        dependencies.settings.input_rate_usd_e5_per_million,
        dependencies.settings.output_rate_usd_e5_per_million,
    )
    client = dependencies.instructor

    async def _bound(
        budget: Any,
        prompt: str,
        model_name: str,
        role: str,
        max_retries: int,
    ) -> tuple[FinalAnswer, int]:
        parsed, cost = await base(client, prompt, model_name, role, max_retries)
        # Record the real usage on the per-request BudgetGuard; the
        # base helper returned the integer cost already.
        if cost:
            budget.add_cost(cost)
        return parsed, cost

    return _bound


async def synthesis_body_for_tests(
    state: Mapping[str, object],
    *,
    dependencies: AgentDependencies,
    cost_recorder: CostRecorder = _default_cost_recorder,
    to_thread: Callable[..., Awaitable[FinalAnswer]] | None = None,
    synthesizer: UsageAwareSynthesizer | None = None,
) -> Mapping[str, object]:
    return await _synthesis_body(
        state,
        dependencies=dependencies,
        cost_recorder=cost_recorder,
        to_thread=to_thread,
        synthesizer=synthesizer,
    )


__all__ = [
    "MAX_DOCS_IN_PROMPT",
    "SYNTHESIS_DEADLINE_SECONDS",
    "Citation",
    "FinalAnswer",
    "make_synthesis_agent",
    "synthesis_body_for_tests",
]
