"""Retrieval agent node — thin adapter over W7D3 ``retrieve_and_generate``.

Does **not** re-implement dense/sparse/RRF/MMR/rerank. Instead, it:

1. Optionally asks an injected model to rewrite the question in a way
   that preserves identifiers (``ord-synth-9001``, ``tenant-a``, digits)
   and stays short. Empty rewrites fall back to the original question.
2. Delegates to the injected retrieval callable via
   :func:`asyncio.to_thread` — the W7D3 callable is synchronous.
3. Adapts the W7D3 return value (``answer`` + ``citations``) into up to
   ``TOP_DOCS`` bounded docs and drops any bulky metadata.

The retrieval callable is a Protocol, so unit tests can hand in a
deterministic fake and never touch pgvector or Redis.
"""

from __future__ import annotations

import asyncio
import re
from collections.abc import Awaitable, Callable, Mapping

from langsmith import traceable

from ..budgets import BudgetExceeded
from ..dependencies import (
    AgentDependencies,
    RetrievalCallable,
    get_request_context,
)
from ._deadline import deadline

RETRIEVAL_DEADLINE_SECONDS = 3.0
TOP_DOCS = 8
MAX_QUOTE_CHARS = 240

_TIMEOUT_SENTINEL: dict[str, object] = {
    "docs": [],
    "visited_nodes": ["retrieval_agent"],
    "errors": ["retrieval_deadline_exceeded"],
    "cost_usd_e5": 0,
}

# Identifier patterns that must survive any query rewrite. Concretely:
# order ids (``ord-*``), tenant ids (``tenant-*``), and standalone digit
# runs of 3+ characters. If the rewrite drops any of these, we fall back
# to the original question.
_ID_PATTERNS = (
    re.compile(r"\bord-[a-z0-9-]+", re.IGNORECASE),
    re.compile(r"\btenant-[a-z]", re.IGNORECASE),
    re.compile(r"\b\d{3,}\b"),
)


# Rewriter injection point: production wires this to an Anthropic
# ``messages.create`` call; tests inject a deterministic fake.
QueryRewriter = Callable[[str], Awaitable[str]]


async def _identity_rewriter(question: str) -> str:
    return question


def _identifiers(text: str) -> set[str]:
    hits: set[str] = set()
    for pat in _ID_PATTERNS:
        hits.update(m.group(0).lower() for m in pat.finditer(text))
    return hits


def _pick_rewrite(original: str, rewrite: str) -> str:
    """Return the rewrite iff it is bounded and preserves identifiers."""
    rewritten = (rewrite or "").strip()
    if not rewritten:
        return original
    if len(rewritten) > 400:
        return original
    if not _identifiers(original).issubset(_identifiers(rewritten)):
        return original
    return rewritten


def _adapt_docs(payload: Mapping[str, object]) -> list[dict[str, object]]:
    """Convert a W7D3 retrieval return to the bounded doc list state schema.

    W7D3 emits ``answer`` + ``citations`` (each a dict with ``chunk_id``
    / ``doc_id`` / ``tenant_id``). We keep only chunk_id / doc_id and,
    optionally, a bounded quote extracted from the answer. Embeddings
    and internal metadata are dropped.
    """
    citations = payload.get("citations")
    if not isinstance(citations, list):
        return []
    answer = payload.get("answer") if isinstance(payload.get("answer"), str) else ""
    if not isinstance(answer, str):
        answer = ""
    quote = answer[:MAX_QUOTE_CHARS] if answer else ""
    out: list[dict[str, object]] = []
    for entry in citations[:TOP_DOCS]:
        if not isinstance(entry, Mapping):
            continue
        doc: dict[str, object] = {}
        chunk_id = entry.get("chunk_id")
        if isinstance(chunk_id, str):
            doc["chunk_id"] = chunk_id
        doc_id = entry.get("doc_id")
        if isinstance(doc_id, str):
            doc["doc_id"] = doc_id
        score = entry.get("score")
        if isinstance(score, (int, float)) and not isinstance(score, bool):
            doc["score"] = float(score)
        if quote:
            doc["quote"] = quote
        if doc:
            out.append(doc)
    return out


async def _retrieval_body(
    state: Mapping[str, object],
    *,
    dependencies: AgentDependencies,
    rewriter: QueryRewriter = _identity_rewriter,
    to_thread: Callable[..., Awaitable[object]] | None = None,
) -> Mapping[str, object]:
    request_id = state.get("request_id")
    if not isinstance(request_id, str):
        raise ValueError("state must carry a string 'request_id' for node dispatch")
    ctx = get_request_context(request_id)

    original = str(state.get("question", ""))
    tenant_id = str(state.get("tenant_id", ctx.tenant_id))

    # Query rewrite (bounded, identifier-preserving).
    try:
        ctx.budget.check_or_raise()
        rewritten = await rewriter(original)
    except BudgetExceeded:
        return {
            "docs": [],
            "cost_usd_e5": 0,
            "visited_nodes": ["retrieval_agent"],
            "errors": ["budget_exceeded"],
        }
    query = _pick_rewrite(original, rewritten)

    # Delegate to W7D3 retrieval (synchronous, so run on a worker thread).
    runner = to_thread if to_thread is not None else asyncio.to_thread
    retriever: RetrievalCallable = dependencies.retrieve
    try:
        payload = await runner(retriever, query, tenant_id)
    except Exception as exc:
        return {
            "docs": [],
            "cost_usd_e5": 0,
            "visited_nodes": ["retrieval_agent"],
            "errors": [f"retrieval_error:{type(exc).__name__}"],
        }

    if not isinstance(payload, Mapping):
        return {
            "docs": [],
            "cost_usd_e5": 0,
            "visited_nodes": ["retrieval_agent"],
            "errors": ["retrieval_bad_payload"],
        }

    docs = _adapt_docs(payload)
    return {
        "docs": docs,
        "cost_usd_e5": 0,
        "visited_nodes": ["retrieval_agent"],
        "errors": [],
    }


def make_retrieval_agent(
    dependencies: AgentDependencies,
    *,
    rewriter: QueryRewriter = _identity_rewriter,
) -> Callable[[Mapping[str, object]], Awaitable[Mapping[str, object]]]:
    """Return the deadline-wrapped async retrieval node."""

    @deadline(seconds=RETRIEVAL_DEADLINE_SECONDS, sentinel=_TIMEOUT_SENTINEL)
    @traceable(name="retrieval_agent", project_name="expense-agent-svc-dev")
    async def retrieval_agent(state: Mapping[str, object]) -> Mapping[str, object]:
        return await _retrieval_body(state, dependencies=dependencies, rewriter=rewriter)

    return retrieval_agent


async def retrieval_body_for_tests(
    state: Mapping[str, object],
    *,
    dependencies: AgentDependencies,
    rewriter: QueryRewriter = _identity_rewriter,
    to_thread: Callable[..., Awaitable[object]] | None = None,
) -> Mapping[str, object]:
    return await _retrieval_body(
        state, dependencies=dependencies, rewriter=rewriter, to_thread=to_thread
    )


__all__ = [
    "MAX_QUOTE_CHARS",
    "RETRIEVAL_DEADLINE_SECONDS",
    "TOP_DOCS",
    "make_retrieval_agent",
    "retrieval_body_for_tests",
]
