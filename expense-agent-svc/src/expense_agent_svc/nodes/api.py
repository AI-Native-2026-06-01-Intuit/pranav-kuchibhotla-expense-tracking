"""API agent node.

Dynamically discovers the MCP tool catalogue at runtime, translates the
discovered JSON schemas to Anthropic tool-use format, and iterates the
tool-use loop for at most :data:`MAX_TOOL_ITERATIONS` steps. Every write
tool (any tool whose input schema requires ``idempotency_key``) has its
key replaced with a deterministic UUID v5 derived from
``(thread_id, tool_name, canonical args hash)`` so a checkpoint replay
produces the identical key and the upstream ledger deduplicates.

The Anthropic client and MCP session are injected through
:class:`AgentDependencies`; nothing in this module reads real
credentials or constructs a real client. The ``X-Agent`` header
convention lives on the injected client (the FastAPI lifespan will
wire it up in Phase 14).
"""

from __future__ import annotations

import hashlib
import json
import uuid
from collections.abc import Awaitable, Callable, Mapping

from langsmith import traceable

from ..budgets import BudgetExceeded
from ..dependencies import (
    AgentDependencies,
    BudgetGuardLike,
    MCPSessionLike,
    get_request_context_for_state,
)
from ._deadline import deadline

# --- Constants ---
API_DEADLINE_SECONDS = 5.0
MAX_TOOL_ITERATIONS = 5
MAX_STORED_RESULTS = 8
MAX_RESULT_CHARS = 4_000

# Fixed namespace for W7D5 deterministic idempotency keys. A stable
# constant is required so a checkpoint replay across a pod restart
# regenerates the same UUID5. Do not change without a migration plan.
UUID5_NAMESPACE = uuid.UUID("2f3b3a5c-6d4e-5a7b-8c9d-1e2f3a4b5c6d")

_TIMEOUT_SENTINEL: dict[str, object] = {
    "tool_results": {},
    "visited_nodes": ["api_agent"],
    "errors": ["api_deadline_exceeded"],
    "cost_usd_e5": 0,
}


def canonical_args_hash(args: Mapping[str, object]) -> str:
    """SHA-256 hex digest of the canonical JSON of ``args``.

    Excludes ``idempotency_key`` from the payload so a replay whose
    args already carry a key produces the identical hash and,
    therefore, the identical UUID5. Sorted keys + minimal separators
    guarantee byte-stable input.
    """
    cleaned = {k: v for k, v in args.items() if k != "idempotency_key"}
    payload = json.dumps(cleaned, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def deterministic_idempotency_key(
    thread_id: str,
    tool_name: str,
    arguments: Mapping[str, object],
) -> uuid.UUID:
    """Return a UUID v5 derived from ``(thread_id, tool_name, args_hash)``.

    The MCP server's schema now accepts UUID v4 or v5 (see the W7D4
    compatibility change), so this key traverses the wire unchanged.
    """
    seed = f"{thread_id}|{tool_name}|{canonical_args_hash(arguments)}"
    key = uuid.uuid5(UUID5_NAMESPACE, seed)
    assert key.version == 5, "deterministic key must be UUID v5"
    return key


def _tool_requires_idempotency_key(tool_schema: Mapping[str, object]) -> bool:
    """Detect a write tool by 'idempotency_key' in the schema's required list."""
    required = tool_schema.get("required")
    if isinstance(required, list):
        return "idempotency_key" in required
    props = tool_schema.get("properties")
    return isinstance(props, dict) and "idempotency_key" in props


def _tool_supports_tenant(tool_schema: Mapping[str, object]) -> bool:
    props = tool_schema.get("properties")
    return isinstance(props, dict) and "tenant_id" in props


def _mcp_tool_to_anthropic(tool: object) -> dict[str, object]:
    """Convert an MCP :class:`mcp.types.Tool` to an Anthropic tool definition.

    Uses ``getattr`` so we do not import ``mcp.types.Tool`` at type
    level — tests inject small fakes with the same attribute names.
    """
    name = getattr(tool, "name", None)
    description = getattr(tool, "description", None) or ""
    input_schema = getattr(tool, "inputSchema", None) or {}
    if not isinstance(name, str) or not name:
        raise ValueError("discovered MCP tool without a name; refusing to translate")
    if not isinstance(input_schema, dict):
        raise ValueError(f"tool {name!r} has non-dict inputSchema")
    return {
        "name": name,
        "description": description,
        "input_schema": input_schema,
    }


async def _list_tool_catalogue(session: MCPSessionLike) -> list[dict[str, object]]:
    """Discover tools from the MCP session; production must not hardcode this."""
    listing = await session.list_tools()
    tools = getattr(listing, "tools", None)
    if tools is None and isinstance(listing, list):
        tools = listing
    if not isinstance(tools, list):
        raise ValueError("MCP list_tools() returned no 'tools' attribute or list")
    return [_mcp_tool_to_anthropic(t) for t in tools]


def _bound_result_content(content: object) -> object:
    """Coerce MCP tool result content to a JSON-serializable, bounded blob."""
    if isinstance(content, (str, int, float, bool)) or content is None:
        text = str(content)
        return text[:MAX_RESULT_CHARS]
    if isinstance(content, list):
        out: list[object] = []
        for item in content[:MAX_STORED_RESULTS]:
            item_text = getattr(item, "text", None)
            if isinstance(item_text, str):
                out.append(item_text[:MAX_RESULT_CHARS])
            else:
                out.append(str(item)[:MAX_RESULT_CHARS])
        return out
    if isinstance(content, Mapping):
        return {k: str(v)[:MAX_RESULT_CHARS] for k, v in list(content.items())[:MAX_STORED_RESULTS]}
    return str(content)[:MAX_RESULT_CHARS]


def _prepare_tool_arguments(
    *,
    thread_id: str,
    tenant_id: str,
    tool_name: str,
    tool_schema: Mapping[str, object],
    raw_arguments: Mapping[str, object],
) -> dict[str, object]:
    """Return a defensive copy of ``raw_arguments`` with tenant + UUID5 fixed.

    * Model-provided tenant is always overwritten with the request tenant
      when the schema supports it — model-provided tenant escalation is
      never allowed.
    * If the tool's schema requires ``idempotency_key``, the deterministic
      UUID5 is injected. Any model-provided arbitrary key is replaced.
    """
    args = dict(raw_arguments)
    if _tool_supports_tenant(tool_schema):
        args["tenant_id"] = tenant_id
    if _tool_requires_idempotency_key(tool_schema):
        args["idempotency_key"] = str(deterministic_idempotency_key(thread_id, tool_name, args))
    return args


# Cost estimator injection: production wires this to token accounting via
# ``BudgetGuard.record_usage``. Tests inject a small fake that returns a
# fixed integer cost per model call.
CostRecorder = Callable[[BudgetGuardLike, object], int]


def _default_cost_recorder(budget: BudgetGuardLike, response: object) -> int:
    """Attribute Anthropic usage to the budget; missing usage counts as zero.

    Real token rates live in :mod:`expense_agent_svc.settings` and are
    wired here in Phase 14; for now we conservatively pass zero and
    document that the llm-proxy metric remains authoritative.
    """
    usage = getattr(response, "usage", None)
    if usage is None:
        return 0
    input_tokens = int(getattr(usage, "input_tokens", 0) or 0)
    output_tokens = int(getattr(usage, "output_tokens", 0) or 0)
    added: int = budget.record_usage(
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        input_rate_usd_e5_per_million=0,
        output_rate_usd_e5_per_million=0,
    )
    return added


# The Anthropic tool-loop is expressed as a strategy so tests can drive
# it deterministically without importing anthropic. It receives the
# discovered tool catalogue and the running message list and returns the
# next model response object.
ModelInvoke = Callable[[list[dict[str, object]], list[dict[str, object]]], Awaitable[object]]


def _extract_stop_reason(response: object) -> str | None:
    stop = getattr(response, "stop_reason", None)
    return stop if isinstance(stop, str) else None


def _extract_tool_uses(response: object) -> list[dict[str, object]]:
    """Return the tool-use blocks from an Anthropic response."""
    content = getattr(response, "content", None) or []
    out: list[dict[str, object]] = []
    for block in content:
        if getattr(block, "type", None) != "tool_use":
            continue
        name = getattr(block, "name", None)
        raw_args = getattr(block, "input", {}) or {}
        block_id = getattr(block, "id", None)
        if not isinstance(name, str):
            continue
        if not isinstance(raw_args, Mapping):
            continue
        out.append(
            {
                "id": str(block_id) if block_id is not None else "",
                "name": name,
                "input": dict(raw_args),
            }
        )
    return out


async def _api_agent_body(
    state: Mapping[str, object],
    *,
    dependencies: AgentDependencies,
    model_invoke: ModelInvoke,
    cost_recorder: CostRecorder = _default_cost_recorder,
) -> Mapping[str, object]:
    request_ctx = get_request_context_for_state(state)
    budget = request_ctx.budget

    catalogue = await _list_tool_catalogue(dependencies.mcp_session)
    schema_by_name = {t["name"]: t["input_schema"] for t in catalogue}

    tool_results: dict[str, object] = {}
    delta_cost = 0
    errors: list[str] = []

    messages: list[dict[str, object]] = [
        {"role": "user", "content": str(state.get("question", ""))}
    ]

    try:
        for _ in range(MAX_TOOL_ITERATIONS):
            budget.check_or_raise()
            response = await model_invoke(catalogue, messages)
            delta_cost += cost_recorder(budget, response)

            stop_reason = _extract_stop_reason(response)
            tool_uses = _extract_tool_uses(response)

            if stop_reason != "tool_use" or not tool_uses:
                break

            # Assistant turn with tool_use blocks becomes part of history.
            messages.append({"role": "assistant", "content": getattr(response, "content", [])})

            tool_result_blocks: list[dict[str, object]] = []
            for use in tool_uses:
                name = str(use["name"])
                schema = schema_by_name.get(name, {})
                if not isinstance(schema, Mapping):
                    schema = {}
                prepared = _prepare_tool_arguments(
                    thread_id=request_ctx.thread_id,
                    tenant_id=request_ctx.tenant_id,
                    tool_name=name,
                    tool_schema=schema,
                    raw_arguments=use["input"],  # type: ignore[arg-type]
                )
                mcp_result = await dependencies.mcp_session.call_tool(name, prepared)
                bounded = _bound_result_content(getattr(mcp_result, "content", mcp_result))
                # Keep the last write for a given tool key inside a
                # single node run; the tool_results reducer at the graph
                # level preserves earlier writes across the fan-in.
                tool_results[name] = bounded
                tool_result_blocks.append(
                    {
                        "type": "tool_result",
                        "tool_use_id": str(use["id"]),
                        "content": str(bounded)[:MAX_RESULT_CHARS],
                    }
                )
                if len(tool_results) >= MAX_STORED_RESULTS:
                    break

            messages.append({"role": "user", "content": tool_result_blocks})
    except BudgetExceeded:
        errors.append("budget_exceeded")

    return {
        "tool_results": tool_results,
        "cost_usd_e5": delta_cost,
        "visited_nodes": ["api_agent"],
        "errors": errors,
    }


def make_api_agent(
    dependencies: AgentDependencies,
    *,
    model_invoke: ModelInvoke,
    cost_recorder: CostRecorder = _default_cost_recorder,
) -> Callable[[Mapping[str, object]], Awaitable[Mapping[str, object]]]:
    """Return the deadline-wrapped async node bound to ``dependencies``."""

    @deadline(seconds=API_DEADLINE_SECONDS, sentinel=_TIMEOUT_SENTINEL)
    @traceable(name="api_agent", project_name="expense-agent-svc-dev")
    async def api_agent(state: Mapping[str, object]) -> Mapping[str, object]:
        return await _api_agent_body(
            state,
            dependencies=dependencies,
            model_invoke=model_invoke,
            cost_recorder=cost_recorder,
        )

    return api_agent


# --- Test-only helpers exposed for direct unit tests ---


async def api_agent_body_for_tests(
    state: Mapping[str, object],
    *,
    dependencies: AgentDependencies,
    model_invoke: ModelInvoke,
    cost_recorder: CostRecorder = _default_cost_recorder,
) -> Mapping[str, object]:
    """Expose the untimed inner body so tests can assert on the loop mechanics."""
    return await _api_agent_body(
        state,
        dependencies=dependencies,
        model_invoke=model_invoke,
        cost_recorder=cost_recorder,
    )


__all__ = [
    "API_DEADLINE_SECONDS",
    "MAX_RESULT_CHARS",
    "MAX_STORED_RESULTS",
    "MAX_TOOL_ITERATIONS",
    "UUID5_NAMESPACE",
    "api_agent_body_for_tests",
    "canonical_args_hash",
    "deterministic_idempotency_key",
    "make_api_agent",
]
