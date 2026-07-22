"""``rag.retrieve_and_generate`` tool.

Calls the W7D3 in-process pipeline (:func:`expense_ai.rag.retrieve_and_generate`)
via ``asyncio.to_thread`` — the pipeline is synchronous — with a hard
wall-clock budget from ``EXPENSE_MCP_TOOL_TIMEOUT_RAG_S``. Timeouts map
to the dedicated MCP code 5040.

The upstream returns a permissive ``dict[str, object]`` whose keys and
citation shape are internal to expense-ai. The adapter is deliberately
strict about the DTO it hands back: we drop ``cache_hit`` and any other
internal fields, truncate citations to ``top_k``, and coerce the score
field to a plain float. See ``docs/evidence/w7d4-static-validation.md``
for the field-mapping table.
"""

import asyncio
import time
from typing import Any

from langsmith import traceable
from mcp.server.fastmcp import Context

from ..app import deps_from, mcp
from ..auth import assert_tenant_matches
from ..errors import rag_timeout
from ..telemetry import get_logger
from .schemas import Citation, RagAnswer, RagArgs

_log = get_logger("expense_mcp_server.tools.rag")


_RAG_DESCRIPTION = (
    "Answer an expense-domain question using the W7D3 hybrid retrieval "
    "pipeline: dense pgvector + BM25 fusion, MMR diversification, and "
    "BGE reranking, followed by an Anthropic call constrained to the "
    "retrieved context. Use this tool whenever the caller needs a "
    "grounded answer with chunk-level citations (Schedule C rules, "
    "IRS guidance, internal policy). Do NOT use this tool for "
    "free-form chit-chat, code generation, or questions unrelated to "
    "expense classification — call llm.chat instead. Citations are "
    "truncated to top_k and scores are floats. Example: "
    "rag.retrieve_and_generate(question='is a laptop deductible?', "
    "tenant_id='tenant-a', top_k=6) returns a RagAnswer with answer "
    "and citations."
)


def _shape_answer(raw: dict[str, Any], top_k: int) -> RagAnswer:
    """Coerce the permissive expense-ai payload into a strict RagAnswer."""
    answer_text = str(raw.get("answer", ""))
    citations_raw = raw.get("citations") or []
    citations: list[Citation] = []
    for entry in citations_raw[:top_k]:
        if not isinstance(entry, dict):
            continue
        chunk_id = entry.get("chunk_id") or entry.get("id") or ""
        doc_id = entry.get("doc_id") or ""
        score_val = entry.get("score", 0.0)
        try:
            score = float(score_val)
        except (TypeError, ValueError):
            score = 0.0
        citations.append(Citation(chunk_id=str(chunk_id), doc_id=str(doc_id), score=score))

    coverage_val = raw.get("coverage", 0.0)
    try:
        coverage = float(coverage_val)
    except (TypeError, ValueError):
        coverage = 0.0

    rerank_timed_out = bool(raw.get("rerank_timed_out", False))

    return RagAnswer(
        answer=answer_text,
        citations=citations,
        coverage=coverage,
        rerank_timed_out=rerank_timed_out,
    )


async def _run_pipeline(rag_call: Any, args: RagArgs, timeout_s: float) -> dict[str, Any]:
    """Execute the sync pipeline off the event loop with a hard budget."""

    def _invoke() -> dict[str, Any]:
        # ``rag_call`` may be the real ``expense_ai.rag.retrieve_and_generate``
        # (which pulls anthropic/conn/redis from module-level state in prod)
        # or a fake injected by the test suite. Both shapes accept the
        # positional ``query_text`` and ``tenant_id`` and ignore extra
        # kwargs the adapter does not need to compute.
        result = rag_call(
            args.question,
            args.tenant_id,
            top_k=args.top_k,
        )
        if not isinstance(result, dict):
            return {}
        return result

    try:
        raw = await asyncio.wait_for(asyncio.to_thread(_invoke), timeout=timeout_s)
    except TimeoutError as exc:
        raise rag_timeout(args.question[:80]) from exc
    return raw


@mcp.tool(name="rag.retrieve_and_generate", description=_RAG_DESCRIPTION)
@traceable(name="rag.retrieve_and_generate", run_type="chain")
async def retrieve_and_generate(
    question: str,
    tenant_id: str,
    top_k: int,
    ctx: Context,  # type: ignore[type-arg]
) -> RagAnswer:
    args = RagArgs(question=question, tenant_id=tenant_id, top_k=top_k)
    assert_tenant_matches(args.tenant_id)

    deps = deps_from(ctx)
    started = time.perf_counter()
    _log.info("tool.invoke.start", tool="rag.retrieve_and_generate", tenant_id=args.tenant_id)

    raw = await _run_pipeline(deps.rag_call, args, deps.settings.tool_timeout_rag_s)
    answer = _shape_answer(raw, args.top_k)

    duration_ms = int((time.perf_counter() - started) * 1000)
    _log.info(
        "tool.invoke.end",
        tool="rag.retrieve_and_generate",
        tenant_id=args.tenant_id,
        duration_ms=duration_ms,
        cost_usd_minor=0,
        n_citations=len(answer.citations),
    )
    return answer


__all__ = ["retrieve_and_generate"]
