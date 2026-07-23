"""API agent node contract.

Cover:

* Dynamic tool discovery via ``session.list_tools()`` (no hardcoded
  catalogue path).
* Model iteration is capped at :data:`MAX_TOOL_ITERATIONS` = 5.
* Non-tool stop reason exits the loop.
* Deterministic UUID5 idempotency: same inputs -> same key (version 5);
  changed thread/tool/args changes the key; any model-provided key is
  replaced.
* Model-provided ``tenant_id`` is always overwritten with the request
  tenant.
* Read-only tools do not receive an idempotency key.
* Tool results are bounded and JSON-serializable.
* Budget is checked before every model call; usage is recorded.
* ``call_tool`` receives only the arguments dict (no unsupported
  ``headers=`` kwarg).
* The node returns the timeout sentinel shape when the deadline fires.
"""

from __future__ import annotations

import uuid
from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass, field
from typing import Any

import pytest

from expense_agent_svc.budgets import BudgetGuard
from expense_agent_svc.dependencies import (
    AgentDependencies,
    RequestContext,
    register_request,
    release_request,
)
from expense_agent_svc.nodes.api import (
    MAX_TOOL_ITERATIONS,
    api_agent_body_for_tests,
    canonical_args_hash,
    deterministic_idempotency_key,
    make_api_agent,
)
from expense_agent_svc.settings import Settings

# ---------- Fake MCP tool objects ----------


@dataclass
class _FakeTool:
    name: str
    description: str
    inputSchema: dict[str, object]


@dataclass
class _FakeToolListing:
    tools: list[_FakeTool]


ORDERS_GET_SCHEMA: dict[str, object] = {
    "type": "object",
    "properties": {
        "order_id": {"type": "string"},
        "tenant_id": {"type": "string"},
    },
    "required": ["order_id", "tenant_id"],
    "additionalProperties": False,
}

ORDERS_REFUND_SCHEMA: dict[str, object] = {
    "type": "object",
    "properties": {
        "order_id": {"type": "string"},
        "amount": {"type": "string"},
        "reason": {"type": "string"},
        "tenant_id": {"type": "string"},
        "idempotency_key": {"type": "string"},
    },
    "required": ["order_id", "amount", "reason", "tenant_id", "idempotency_key"],
    "additionalProperties": False,
}


class _FakeMCPSession:
    def __init__(self) -> None:
        self.list_tools_calls = 0
        self.call_tool_calls: list[tuple[str, dict[str, object]]] = []
        self._catalogue = [
            _FakeTool(
                name="orders.get_order",
                description="Fetch a tenant-scoped order",
                inputSchema=ORDERS_GET_SCHEMA,
            ),
            _FakeTool(
                name="orders.create_refund",
                description="Refund an order idempotently",
                inputSchema=ORDERS_REFUND_SCHEMA,
            ),
        ]

    async def list_tools(self, cursor: str | None = None) -> object:
        self.list_tools_calls += 1
        return _FakeToolListing(tools=list(self._catalogue))

    async def call_tool(
        self,
        name: str,
        arguments: dict[str, object] | None = None,
    ) -> object:
        self.call_tool_calls.append((name, dict(arguments or {})))
        return _FakeCallResult(content=f"result:{name}:{sorted((arguments or {}).items())}")


@dataclass
class _FakeCallResult:
    content: object


@dataclass
class _FakeBlock:
    type: str
    name: str = ""
    id: str = ""
    input: dict[str, object] | None = None


@dataclass
class _FakeUsage:
    input_tokens: int
    output_tokens: int


@dataclass
class _FakeResponse:
    stop_reason: str
    content: list[_FakeBlock]
    usage: _FakeUsage = field(default_factory=lambda: _FakeUsage(1000, 500))


def _make_deps(session: _FakeMCPSession) -> AgentDependencies:
    return AgentDependencies(
        settings=Settings(),
        mcp_session=session,
        anthropic=_StubClient(),
        instructor=_StubClient(),
        retrieve=_stub_retrieve,
    )


def _stub_retrieve(query_text: str, tenant_id: str, /) -> dict[str, object]:
    del query_text, tenant_id
    return {"answer": "stub", "citations": []}


class _StubClient:
    @property
    def messages(self) -> object:  # pragma: no cover
        return object()


def _register_ctx(*, ceiling: int = 25_000) -> RequestContext:
    ctx = RequestContext(
        thread_id="thread-1",
        tenant_id="tenant-a",
        budget=BudgetGuard(ceiling_usd_e5=ceiling),
    )
    register_request(ctx)
    return ctx


# ---------- Deterministic key tests (do not need registry) ----------


def test_canonical_args_hash_stable_and_key_agnostic() -> None:
    a = {"order_id": "ord-1", "amount": "10.00", "tenant_id": "tenant-a"}
    # Same content, different key ordering.
    b = {"tenant_id": "tenant-a", "order_id": "ord-1", "amount": "10.00"}
    assert canonical_args_hash(a) == canonical_args_hash(b)

    # An existing idempotency_key must not perturb the hash — replay
    # stability.
    c = {**a, "idempotency_key": "some-uuid"}
    assert canonical_args_hash(a) == canonical_args_hash(c)


def test_deterministic_key_is_uuid5_and_repeats() -> None:
    args = {"order_id": "ord-1", "amount": "10.00", "tenant_id": "tenant-a"}
    k1 = deterministic_idempotency_key("thread-1", "orders.create_refund", args)
    k2 = deterministic_idempotency_key("thread-1", "orders.create_refund", args)
    assert k1 == k2
    assert k1.version == 5


def test_deterministic_key_changes_with_thread_tool_or_args() -> None:
    args = {"order_id": "ord-1", "amount": "10.00", "tenant_id": "tenant-a"}
    base = deterministic_idempotency_key("thread-1", "orders.create_refund", args)
    assert base != deterministic_idempotency_key("thread-2", "orders.create_refund", args)
    assert base != deterministic_idempotency_key("thread-1", "orders.other_write", args)
    other = {**args, "order_id": "ord-2"}
    assert base != deterministic_idempotency_key("thread-1", "orders.create_refund", other)


# ---------- Loop-body tests ----------


ModelInvoke = Callable[[list[dict[str, object]], list[dict[str, object]]], Awaitable[Any]]


def _make_scripted_invoke(script: list[_FakeResponse]) -> tuple[ModelInvoke, list[int]]:
    calls: list[int] = []

    async def invoke(
        catalogue: list[dict[str, object]],
        messages: list[dict[str, object]],
    ) -> _FakeResponse:
        del catalogue, messages
        idx = len(calls)
        calls.append(idx)
        if idx >= len(script):
            # Any further call means the loop failed to terminate.
            raise AssertionError("model was invoked more times than scripted")
        return script[idx]

    return invoke, calls


@pytest.mark.asyncio
async def test_api_node_calls_list_tools_and_translates_catalogue() -> None:
    session = _FakeMCPSession()
    deps = _make_deps(session)
    ctx = _register_ctx()

    # The scripted invoke is not used in this test — we build a bespoke
    # ``observe`` invoker below to capture the catalogue passed to the model.
    _make_scripted_invoke(
        [
            _FakeResponse(
                stop_reason="end_turn",
                content=[_FakeBlock(type="text")],
            )
        ]
    )

    try:
        seen_catalogue: list[list[dict[str, object]]] = []

        async def observe(
            catalogue: list[dict[str, object]],
            messages: list[dict[str, object]],
        ) -> _FakeResponse:
            del messages
            seen_catalogue.append(catalogue)
            return _FakeResponse(
                stop_reason="end_turn",
                content=[_FakeBlock(type="text")],
            )

        await api_agent_body_for_tests(
            {
                "question": "get me ord-synth-9001",
                "tenant_id": "tenant-a",
                "thread_id": "thread-1",
                "request_id": ctx.request_id,
            },
            dependencies=deps,
            model_invoke=observe,
            cost_recorder=lambda budget, response: 0,
        )
    finally:
        release_request(ctx.request_id)

    assert session.list_tools_calls == 1
    assert seen_catalogue, "model was not invoked"
    names = {t["name"] for t in seen_catalogue[0]}
    assert names == {"orders.get_order", "orders.create_refund"}
    # Anthropic tool-use shape: input_schema/description/name.
    for tool in seen_catalogue[0]:
        assert set(tool.keys()) >= {"name", "description", "input_schema"}


@pytest.mark.asyncio
async def test_api_node_caps_iterations_at_max() -> None:
    session = _FakeMCPSession()
    deps = _make_deps(session)
    ctx = _register_ctx()

    # Every response says "tool_use" and re-invokes get_order.
    tool_use = _FakeResponse(
        stop_reason="tool_use",
        content=[
            _FakeBlock(
                type="tool_use",
                name="orders.get_order",
                id="tu-0",
                input={"order_id": "ord-1"},
            )
        ],
    )
    script = [tool_use for _ in range(MAX_TOOL_ITERATIONS + 5)]
    invoke, calls = _make_scripted_invoke(script)

    try:
        await api_agent_body_for_tests(
            {
                "question": "lookup order",
                "tenant_id": "tenant-a",
                "thread_id": "thread-1",
                "request_id": ctx.request_id,
            },
            dependencies=deps,
            model_invoke=invoke,
            cost_recorder=lambda budget, response: 0,
        )
    finally:
        release_request(ctx.request_id)

    assert len(calls) == MAX_TOOL_ITERATIONS


@pytest.mark.asyncio
async def test_api_node_stops_on_non_tool_use_response() -> None:
    session = _FakeMCPSession()
    deps = _make_deps(session)
    ctx = _register_ctx()

    invoke, calls = _make_scripted_invoke(
        [
            _FakeResponse(
                stop_reason="end_turn",
                content=[_FakeBlock(type="text")],
            )
        ]
    )

    try:
        result = await api_agent_body_for_tests(
            {
                "question": "hello",
                "tenant_id": "tenant-a",
                "thread_id": "thread-1",
                "request_id": ctx.request_id,
            },
            dependencies=deps,
            model_invoke=invoke,
            cost_recorder=lambda budget, response: 0,
        )
    finally:
        release_request(ctx.request_id)

    assert len(calls) == 1
    assert result["visited_nodes"] == ["api_agent"]
    assert result["tool_results"] == {}


@pytest.mark.asyncio
async def test_api_node_forces_tenant_and_injects_uuid5() -> None:
    session = _FakeMCPSession()
    deps = _make_deps(session)
    ctx = _register_ctx()

    # Model tries to write with a wrong tenant and a placeholder key.
    tool_use = _FakeResponse(
        stop_reason="tool_use",
        content=[
            _FakeBlock(
                type="tool_use",
                name="orders.create_refund",
                id="tu-1",
                input={
                    "order_id": "ord-synth-9001",
                    "amount": "10.00",
                    "reason": "dupe charge",
                    "tenant_id": "tenant-b",  # attempted override
                    "idempotency_key": "attacker-picked-key",
                },
            )
        ],
    )
    end_turn = _FakeResponse(stop_reason="end_turn", content=[_FakeBlock(type="text")])
    invoke, _calls = _make_scripted_invoke([tool_use, end_turn])

    try:
        await api_agent_body_for_tests(
            {
                "question": "please refund",
                "tenant_id": "tenant-a",
                "thread_id": "thread-1",
                "request_id": ctx.request_id,
            },
            dependencies=deps,
            model_invoke=invoke,
            cost_recorder=lambda budget, response: 0,
        )
    finally:
        release_request(ctx.request_id)

    assert len(session.call_tool_calls) == 1
    name, sent_args = session.call_tool_calls[0]
    assert name == "orders.create_refund"
    assert sent_args["tenant_id"] == "tenant-a", "model override must not survive"

    idem = sent_args["idempotency_key"]
    assert isinstance(idem, str)
    parsed = uuid.UUID(idem)
    assert parsed.version == 5
    # Deterministic: matches the direct computation on the canonicalized args.
    expected = str(
        deterministic_idempotency_key(
            "thread-1",
            "orders.create_refund",
            {
                "order_id": "ord-synth-9001",
                "amount": "10.00",
                "reason": "dupe charge",
                "tenant_id": "tenant-a",
            },
        )
    )
    assert idem == expected


@pytest.mark.asyncio
async def test_api_node_read_only_tool_gets_no_idempotency_key() -> None:
    session = _FakeMCPSession()
    deps = _make_deps(session)
    ctx = _register_ctx()

    tool_use = _FakeResponse(
        stop_reason="tool_use",
        content=[
            _FakeBlock(
                type="tool_use",
                name="orders.get_order",
                id="tu-2",
                input={"order_id": "ord-synth-9001"},
            )
        ],
    )
    end_turn = _FakeResponse(stop_reason="end_turn", content=[_FakeBlock(type="text")])
    invoke, _calls = _make_scripted_invoke([tool_use, end_turn])

    try:
        await api_agent_body_for_tests(
            {
                "question": "get order",
                "tenant_id": "tenant-a",
                "thread_id": "thread-1",
                "request_id": ctx.request_id,
            },
            dependencies=deps,
            model_invoke=invoke,
            cost_recorder=lambda budget, response: 0,
        )
    finally:
        release_request(ctx.request_id)

    _name, sent_args = session.call_tool_calls[0]
    assert "idempotency_key" not in sent_args


@pytest.mark.asyncio
async def test_api_node_records_cost_and_returns_bounded_results() -> None:
    session = _FakeMCPSession()
    deps = _make_deps(session)
    ctx = _register_ctx()

    tool_use = _FakeResponse(
        stop_reason="tool_use",
        content=[
            _FakeBlock(
                type="tool_use",
                name="orders.get_order",
                id="tu-3",
                input={"order_id": "ord-1"},
            )
        ],
    )
    end_turn = _FakeResponse(stop_reason="end_turn", content=[_FakeBlock(type="text")])
    invoke, _calls = _make_scripted_invoke([tool_use, end_turn])

    def record_10(budget: object, response: object) -> int:
        del response
        assert isinstance(budget, BudgetGuard)
        budget.add_cost(10)
        return 10

    try:
        result = await api_agent_body_for_tests(
            {
                "question": "get order",
                "tenant_id": "tenant-a",
                "thread_id": "thread-1",
                "request_id": ctx.request_id,
            },
            dependencies=deps,
            model_invoke=invoke,
            cost_recorder=record_10,
        )
    finally:
        release_request(ctx.request_id)

    # Two model calls -> 20 cost_usd_e5.
    assert result["cost_usd_e5"] == 20
    # Tool result was bounded to a JSON-serializable primitive.
    tool_results = result["tool_results"]
    assert isinstance(tool_results, dict)
    stored = tool_results.get("orders.get_order")
    assert isinstance(stored, str)
    assert len(stored) <= 4_000


@pytest.mark.asyncio
async def test_api_node_stops_when_budget_exhausted_before_call() -> None:
    session = _FakeMCPSession()
    deps = _make_deps(session)
    ctx = _register_ctx(ceiling=5)

    tool_use = _FakeResponse(
        stop_reason="tool_use",
        content=[
            _FakeBlock(
                type="tool_use",
                name="orders.get_order",
                id="tu-4",
                input={"order_id": "ord-1"},
            )
        ],
    )
    invoke, _calls = _make_scripted_invoke([tool_use, tool_use, tool_use])

    def record_5(budget: object, response: object) -> int:
        del response
        assert isinstance(budget, BudgetGuard)
        budget.add_cost(5)
        return 5

    try:
        result = await api_agent_body_for_tests(
            {
                "question": "get order",
                "tenant_id": "tenant-a",
                "thread_id": "thread-1",
                "request_id": ctx.request_id,
            },
            dependencies=deps,
            model_invoke=invoke,
            cost_recorder=record_5,
        )
    finally:
        release_request(ctx.request_id)

    assert result["errors"] == ["budget_exceeded"]


@pytest.mark.asyncio
async def test_api_node_wrapper_returns_sentinel_on_deadline() -> None:
    import asyncio

    session = _FakeMCPSession()
    deps = _make_deps(session)
    ctx = _register_ctx()

    # Build the wrapped node, but override the deadline to something
    # tiny for the test by re-wrapping the raw body.
    async def slow_invoke(
        catalogue: list[dict[str, object]],
        messages: list[dict[str, object]],
    ) -> _FakeResponse:
        del catalogue, messages
        await asyncio.sleep(1.0)
        return _FakeResponse(stop_reason="end_turn", content=[_FakeBlock(type="text")])

    # Direct wrapper — reuse deadline decorator with a short budget.
    from expense_agent_svc.nodes._deadline import deadline

    @deadline(
        seconds=0.05,
        sentinel={
            "tool_results": {},
            "visited_nodes": ["api_agent"],
            "errors": ["api_deadline_exceeded"],
            "cost_usd_e5": 0,
        },
    )
    async def wrapped(state: Mapping[str, object]) -> Mapping[str, object]:
        return await api_agent_body_for_tests(
            state,
            dependencies=deps,
            model_invoke=slow_invoke,
            cost_recorder=lambda budget, response: 0,
        )

    try:
        result = await wrapped(
            {
                "question": "get order",
                "tenant_id": "tenant-a",
                "thread_id": "thread-1",
                "request_id": ctx.request_id,
            }
        )
    finally:
        release_request(ctx.request_id)

    assert result["errors"] == ["api_deadline_exceeded"]
    assert result["visited_nodes"] == ["api_agent"]
    assert result["deadline_exceeded"] is True


def test_make_api_agent_returns_callable() -> None:
    session = _FakeMCPSession()
    deps = _make_deps(session)

    async def invoke(
        catalogue: list[dict[str, object]],
        messages: list[dict[str, object]],
    ) -> _FakeResponse:
        del catalogue, messages
        return _FakeResponse(stop_reason="end_turn", content=[_FakeBlock(type="text")])

    node = make_api_agent(deps, model_invoke=invoke)
    assert callable(node)
