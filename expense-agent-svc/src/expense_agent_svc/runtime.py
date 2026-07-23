"""Process-scoped runtime for the agent service.

The FastAPI lifespan (:mod:`expense_agent_svc.app`) constructs one
:class:`AgentRuntime` per process. It carries every long-lived
collaborator — Anthropic clients, the MCP session, the compiled
LangGraph, the ``AsyncPostgresSaver`` — that would be wasteful (and
often unsafe) to rebuild on every request.

Critically, this runtime *never* holds a :class:`~expense_agent_svc.
budgets.BudgetGuard`. Budgets are per-request state (each request has
its own ceiling, so sharing one guard would let one tenant starve
another) and are created at the request boundary in Phase 15.

Everything else lives here because it either:

* holds a network transport that must be initialised and torn down
  exactly once (``AsyncPostgresSaver``, ``ClientSession``), or
* is expensive to construct (Anthropic HTTP client with pooled TCP
  connections), or
* would leak a secret at import time if constructed lazily (Anthropic
  API key, MCP bearer JWT).
"""

from __future__ import annotations

import contextlib
from collections.abc import AsyncIterator, Callable
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Protocol, cast

from .dependencies import AgentDependencies
from .settings import Settings

if TYPE_CHECKING:
    from langgraph.checkpoint.base import BaseCheckpointSaver
    from langgraph.graph.state import CompiledStateGraph

    from .state import AgentState


# --- Public runtime ------------------------------------------------------------


@dataclass(frozen=True)
class AgentRuntime:
    """Process-scoped runtime handed to request handlers.

    Only serialisable dependencies enter ``AgentState``; this dataclass
    is deliberately non-serialisable because it must not.

    ``ready`` is a small dict of component-initialisation booleans that
    ``/readyz`` can surface without leaking DSNs, tokens, or internal
    hostnames.
    """

    settings: Settings
    dependencies: AgentDependencies
    graph: CompiledStateGraph[AgentState, Any, AgentState, AgentState]
    checkpointer: BaseCheckpointSaver[Any]
    ready: dict[str, bool]


# --- Factory contract ---------------------------------------------------------


class RuntimeFactory(Protocol):
    """Async context manager that yields an :class:`AgentRuntime`.

    Enter to construct the process-scoped resources; exit to close
    them. Tests inject a fake factory that skips all network I/O; the
    default production factory lives in :func:`default_runtime_factory`.
    """

    def __call__(
        self, settings: Settings
    ) -> contextlib.AbstractAsyncContextManager[AgentRuntime]: ...


# --- X-Agent header constants -------------------------------------------------


X_AGENT_RETRIEVAL = "retrieval_agent"
X_AGENT_API = "api_agent"
X_AGENT_SYNTHESIS = "synthesis_agent"


def anthropic_default_headers(role: str) -> dict[str, str]:
    """Return the default headers each Anthropic client should send.

    ``X-Agent`` is the audit-trail tag the platform side uses to
    attribute spend to a specific worker inside a single request.
    Keeping it as a small helper means the three per-role constants
    stay in exactly one place.
    """
    if role not in {X_AGENT_RETRIEVAL, X_AGENT_API, X_AGENT_SYNTHESIS}:
        raise ValueError(f"unknown X-Agent role: {role!r}")
    return {"X-Agent": role}


# --- Default production factory ----------------------------------------------


def default_runtime_factory(
    settings: Settings,
) -> contextlib.AbstractAsyncContextManager[AgentRuntime]:
    """Return the production runtime factory.

    This function returns an async context manager (via
    :func:`_default_runtime_context`) so callers can ``async with`` it
    inside the FastAPI lifespan. All resource ownership lives inside
    the enclosed :class:`~contextlib.AsyncExitStack` so a failed
    startup unwinds every partially-initialised resource in reverse
    order — no half-opened Postgres connection is left dangling.

    Nothing in this function is invoked at module import; the
    ``import expense_agent_svc.app`` guardrail test proves it.
    """
    return _default_runtime_context(settings)


@contextlib.asynccontextmanager
async def _default_runtime_context(
    settings: Settings,
) -> AsyncIterator[AgentRuntime]:
    """Enter the production runtime.

    Order matters:

    1. Postgres saver (durable checkpoints must be ready before we
       compile the graph).
    2. MCP transport + ``ClientSession`` (the API node needs the
       session to discover tools at first request time).
    3. Three Anthropic clients — one per worker, each with its
       distinct ``X-Agent`` default header.
    4. Instructor wrapper on the synthesis client only.
    5. Compile the graph over the live saver.
    """
    # Late imports so ``import expense_agent_svc.app`` does not pull in
    # anthropic / mcp / langgraph-checkpoint-postgres at process import.
    import instructor as _instructor
    from anthropic import AsyncAnthropic
    from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver
    from mcp import ClientSession
    from mcp.client.sse import sse_client

    from .graph import NodeSet, build_expense_agent_graph
    from .nodes.api import make_api_agent
    from .nodes.retrieval import make_retrieval_agent
    from .nodes.synthesis import make_synthesis_agent

    ready: dict[str, bool] = {
        "postgres_checkpointer": False,
        "mcp_session": False,
        "graph": False,
    }

    async with contextlib.AsyncExitStack() as stack:
        # --- 1. Postgres saver ------------------------------------------
        saver = await stack.enter_async_context(
            AsyncPostgresSaver.from_conn_string(settings.postgres_url)
        )
        await saver.setup()
        ready["postgres_checkpointer"] = True

        # --- 2. MCP SSE transport + session ----------------------------
        bearer = settings.mcp_bearer_jwt.get_secret_value()
        mcp_headers: dict[str, str] = {}
        if bearer:
            mcp_headers["Authorization"] = f"Bearer {bearer}"
        read_stream, write_stream, *_ = await stack.enter_async_context(
            sse_client(settings.mcp_sse_url, headers=mcp_headers or None)
        )
        session = await stack.enter_async_context(ClientSession(read_stream, write_stream))
        await session.initialize()
        ready["mcp_session"] = True

        # --- 3. Anthropic clients per worker ---------------------------
        api_key_value = settings.anthropic_api_key.get_secret_value() or None
        base_url = settings.anthropic_base_url or None

        def _client(role: str) -> AsyncAnthropic:
            return AsyncAnthropic(
                api_key=api_key_value,
                base_url=base_url,
                default_headers=anthropic_default_headers(role),
            )

        retrieval_client = _client(X_AGENT_RETRIEVAL)
        api_client = _client(X_AGENT_API)
        synthesis_raw = _client(X_AGENT_SYNTHESIS)
        # AsyncAnthropic has an ``aclose`` on its underlying HTTPX
        # client; register cleanup so a shutdown unwinds them.
        stack.push_async_callback(retrieval_client.close)
        stack.push_async_callback(api_client.close)
        stack.push_async_callback(synthesis_raw.close)

        # --- 4. Instructor wrapper on the synthesis client only --------
        synthesis_client = _instructor.from_anthropic(synthesis_raw)

        # --- 5. Retrieval callable adapter over W7D3 -------------------
        # Import the real W7D3 entrypoint lazily so it is not required
        # at process import (this keeps ``import expense_agent_svc.app``
        # hermetic for tests).
        from expense_ai.rag import retrieve_and_generate as _retrieve_and_generate

        def _retrieve(query_text: str, tenant_id: str, /) -> dict[str, object]:
            # W7D3 expects a persistent psycopg connection and a redis
            # client — the FastAPI lifespan will populate these in
            # Phase 15 alongside the SSE bridge. Keeping the adapter
            # thin here so Phase 15 owns the pgvector + Redis
            # connections in the same lifespan.
            raise NotImplementedError(
                "retrieval adapter is wired in Phase 15 alongside the SSE bridge; "
                "unit tests should inject a stub retrieve callable."
            )

        # Silence the unused-warning until Phase 15 lands.
        _ = _retrieve_and_generate

        # The real ``ClientSession`` satisfies :class:`MCPSessionLike`
        # structurally, but mypy sees ``list_tools`` returning the
        # concrete ``ListToolsResult`` (a subtype of ``object``) as a
        # variance conflict. Cast at the boundary rather than widening
        # the Protocol return type to ``ListToolsResult`` — the
        # Protocol stays testable with in-memory fakes that return
        # arbitrary listing shapes.
        dependencies = AgentDependencies(
            settings=settings,
            mcp_session=cast(Any, session),
            anthropic=api_client,
            instructor=synthesis_client,
            retrieve=_retrieve,
        )

        # --- 6. Compile the graph over the live saver ------------------
        node_set = NodeSet(
            retrieval_agent=make_retrieval_agent(dependencies),
            api_agent=make_api_agent(
                dependencies,
                model_invoke=_unwired_model_invoke,
            ),
            synthesis_agent=make_synthesis_agent(dependencies),
        )
        graph = build_expense_agent_graph(nodes=node_set, checkpointer=saver)
        ready["graph"] = True

        runtime = AgentRuntime(
            settings=settings,
            dependencies=dependencies,
            graph=graph,
            checkpointer=saver,
            ready=ready,
        )
        yield runtime

    # AsyncExitStack unwinds every resource on exit; nothing extra
    # required here.


async def _unwired_model_invoke(
    catalogue: list[dict[str, object]],
    messages: list[dict[str, object]],
) -> Any:
    """Placeholder API-loop model invoker.

    The real Anthropic tool-loop is wired in Phase 15 (once the SSE
    bridge exists to stream partial tool-use back to the client). This
    stub is here so ``build_expense_agent_graph`` in the default
    runtime can compile without a mid-lifecycle NoneType.
    """
    del catalogue, messages
    raise NotImplementedError("model_invoke is wired in Phase 15 alongside the SSE bridge")


# --- Small helper for tests --------------------------------------------------


FakeRuntimeFactory = Callable[[Settings], contextlib.AbstractAsyncContextManager[AgentRuntime]]

__all__ = [
    "X_AGENT_API",
    "X_AGENT_RETRIEVAL",
    "X_AGENT_SYNTHESIS",
    "AgentRuntime",
    "FakeRuntimeFactory",
    "RuntimeFactory",
    "anthropic_default_headers",
    "default_runtime_factory",
]
