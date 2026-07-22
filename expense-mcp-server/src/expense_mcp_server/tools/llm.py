"""``llm.chat`` tool: bounded chat via the Spring LLM proxy."""

import time
from typing import Any

import httpx
from langsmith import traceable
from mcp.server.fastmcp import Context

from ..app import deps_from, mcp
from ..auth import assert_tenant_matches, bearer_for_upstream
from ..errors import map_http
from ..telemetry import get_logger
from .schemas import ChatAnswer, ChatArgs, ChatMessage

_log = get_logger("expense_mcp_server.tools.llm")


_CHAT_DESCRIPTION = (
    "Ask the shared LLM proxy for a short, tenant-scoped chat "
    "completion with a bounded token budget. Use this tool when you "
    "need a free-form answer that does NOT require the expense "
    "corpus — e.g. reformatting a receipt, summarizing a merchant "
    "description, or generating a short internal explanation. Do NOT "
    "use this tool for questions that must cite Schedule C sources; "
    "call rag.retrieve_and_generate instead so answers stay grounded. "
    "Rate-limited server-side (429s surface as MCP code 4290). "
    "Example: llm.chat(messages=[{'role':'user','content':'summarize "
    "this receipt in one line: ...'}], max_tokens=64, "
    "tenant_id='tenant-a') returns a ChatAnswer with text and usage."
)


async def _chat_impl(client: httpx.AsyncClient, args: ChatArgs, bearer: str) -> ChatAnswer:
    started = time.perf_counter()
    _log.info("tool.invoke.start", tool="llm.chat", tenant_id=args.tenant_id)
    payload = {
        "messages": [m.model_dump() for m in args.messages],
        "max_tokens": args.max_tokens,
        "tenant_id": args.tenant_id,
    }
    headers: dict[str, str] = {}
    token = bearer_for_upstream(bearer)
    if token:
        headers["Authorization"] = f"Bearer {token}"
    resp = await client.post("/api/v1/llm/chat", json=payload, headers=headers)
    duration_ms = int((time.perf_counter() - started) * 1000)

    if resp.status_code != 200:
        err = map_http(resp.status_code, resp.text)
        _log.warning(
            "tool.invoke.end",
            tool="llm.chat",
            tenant_id=args.tenant_id,
            duration_ms=duration_ms,
            cost_usd_minor=0,
            mcp_error_code=err.error.code,
        )
        raise err

    body: dict[str, Any] = resp.json()
    # Pre-shape into a bounded DTO — we deliberately drop upstream keys
    # that are not part of the ChatAnswer contract so a shape drift on
    # the LLM proxy side cannot leak into downstream tool consumers.
    answer = ChatAnswer(
        text=str(body.get("text", "")),
        model=str(body.get("model", "unknown")),
        usage_input_tokens=int(body.get("usage_input_tokens", 0)),
        usage_output_tokens=int(body.get("usage_output_tokens", 0)),
        cost_usd_minor=int(body.get("cost_usd_minor", 0)),
    )
    _log.info(
        "tool.invoke.end",
        tool="llm.chat",
        tenant_id=args.tenant_id,
        duration_ms=duration_ms,
        cost_usd_minor=answer.cost_usd_minor,
    )
    return answer


@mcp.tool(name="llm.chat", description=_CHAT_DESCRIPTION)
@traceable(name="llm.chat", run_type="tool")
async def chat(
    messages: list[dict[str, str]],
    max_tokens: int,
    tenant_id: str,
    ctx: Context,  # type: ignore[type-arg]
) -> ChatAnswer:
    args = ChatArgs(
        messages=[ChatMessage(**m) for m in messages],
        max_tokens=max_tokens,
        tenant_id=tenant_id,
    )
    assert_tenant_matches(args.tenant_id)
    deps = deps_from(ctx)
    bearer = deps.settings.bearer_jwt.get_secret_value()
    return await _chat_impl(deps.llm_client, args, bearer)


__all__ = ["chat"]
