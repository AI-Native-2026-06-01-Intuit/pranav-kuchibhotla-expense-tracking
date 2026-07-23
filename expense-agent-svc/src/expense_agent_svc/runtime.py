"""Process-scoped runtime for the agent service.

The FastAPI lifespan (:mod:`expense_agent_svc.app`) constructs one
:class:`AgentRuntime` per process. It carries every long-lived
collaborator — Anthropic clients, the MCP session, the compiled
LangGraph, the ``AsyncPostgresSaver``, the pgvector pool, and the
Redis client — that would be wasteful (and often unsafe) to rebuild
on every request.

Critically, this runtime *never* holds a
:class:`~expense_agent_svc.budgets.BudgetGuard`. Budgets are
per-request state; sharing one guard across requests would let one
tenant deny another. The request boundary in ``app.py`` constructs
one guard per request.
"""

from __future__ import annotations

import asyncio
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


# --- Configuration errors ---------------------------------------------------


class RuntimeConfigurationError(RuntimeError):
    """Raised when a required runtime configuration is missing.

    The message names the missing environment variable but *never*
    prints its value (which would be a secret for the JWT case). This
    is a startup-time failure — the pod goes to CrashLoopBackoff rather
    than serve unauthenticated MCP traffic.
    """


# --- Public runtime ---------------------------------------------------------


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


# --- Factory contract -------------------------------------------------------


class RuntimeFactory(Protocol):
    """Async context manager that yields an :class:`AgentRuntime`."""

    def __call__(
        self, settings: Settings
    ) -> contextlib.AbstractAsyncContextManager[AgentRuntime]: ...


# --- X-Agent header constants -----------------------------------------------


X_AGENT_RETRIEVAL = "retrieval_agent"
X_AGENT_API = "api_agent"
X_AGENT_SYNTHESIS = "synthesis_agent"


def anthropic_default_headers(role: str) -> dict[str, str]:
    """Return the default headers each Anthropic client should send."""
    if role not in {X_AGENT_RETRIEVAL, X_AGENT_API, X_AGENT_SYNTHESIS}:
        raise ValueError(f"unknown X-Agent role: {role!r}")
    return {"X-Agent": role}


# --- Fail-closed configuration guardrails -----------------------------------


def _require_mcp_configuration(settings: Settings) -> None:
    """Fail-closed check before opening the MCP transport.

    The W7D4 server verifies JWT signature + expiry + audience on
    every SSE request. Starting the runtime without a bearer token
    would produce an infinite loop of authentication rejections that
    look like a network problem in the logs. Fail startup instead so
    the misconfiguration is visible.

    The exception message names the missing environment variable but
    never its value.
    """
    if not settings.mcp_sse_url:
        raise RuntimeConfigurationError(
            "EXPENSE_AGENT_MCP_SSE_URL must be set to start the runtime"
        )
    bearer = settings.mcp_bearer_jwt.get_secret_value()
    if not bearer:
        raise RuntimeConfigurationError(
            "EXPENSE_AGENT_MCP_BEARER_JWT must be set to start the runtime "
            "(the W7D4 SSE middleware refuses unauthenticated requests)"
        )


# --- Real API-loop adapter ---------------------------------------------------


def _translate_tools_for_anthropic(catalogue: list[dict[str, object]]) -> list[dict[str, object]]:
    """Coerce our internal Anthropic tool-use schema to the SDK-safe shape."""
    return [
        {
            "name": tool["name"],
            "description": tool.get("description", ""),
            "input_schema": tool["input_schema"],
        }
        for tool in catalogue
    ]


def make_anthropic_model_invoke(
    *,
    api_client: object,
    model_name: str,
    max_tokens: int = 1024,
) -> Callable[[list[dict[str, object]], list[dict[str, object]]], Any]:
    """Return an async ``model_invoke`` bound to the API-worker client.

    The API node calls this on every tool-use iteration; the returned
    coroutine issues ``messages.create(tools=..., messages=...)`` and
    hands back the raw response so the node can read ``stop_reason``,
    ``content``, and ``usage``. The API worker's ``X-Agent`` header
    lives on ``api_client.default_headers`` so it rides along with every
    request without any per-call plumbing.
    """

    async def invoke(
        catalogue: list[dict[str, object]],
        messages: list[dict[str, object]],
    ) -> Any:
        # ``api_client.messages.create`` returns an
        # ``anthropic.types.Message`` whose ``.usage.input_tokens`` /
        # ``.output_tokens`` are the source of truth for local cost
        # accounting.
        response = await cast(Any, api_client).messages.create(
            model=model_name,
            max_tokens=max_tokens,
            tools=_translate_tools_for_anthropic(catalogue),
            messages=messages,
        )
        return response

    return invoke


# --- Real retrieval adapter -------------------------------------------------


def make_retrieval_callable(
    *,
    pool: object,
    redis_client: object,
    retrieval_anthropic: object,
    settings: Settings,
) -> Callable[[str, str], dict[str, object]]:
    """Return a synchronous ``(query, tenant) -> dict`` adapter for W7D3.

    W7D3 ``retrieve_and_generate`` is synchronous: the retrieval node
    already wraps it in ``asyncio.to_thread``. This adapter grabs a
    connection from the injected psycopg pool for each call and returns
    the borrow to the pool afterwards, so a slow retrieval never
    starves the whole pool.

    The retrieval-worker's ``X-Agent: retrieval_agent`` header lives
    on the injected ``retrieval_anthropic`` client, which W7D3 uses to
    generate its answer text. Passing the async API-worker client into
    W7D3 by mistake would ship the wrong header, so the two roles are
    kept strictly separate.
    """
    from expense_ai.rag import retrieve_and_generate as _retrieve_and_generate

    def _retrieve(query_text: str, tenant_id: str, /) -> dict[str, object]:
        with cast(Any, pool).connection() as conn:
            result: dict[str, object] = _retrieve_and_generate(
                query_text,
                tenant_id,
                anthropic=retrieval_anthropic,
                conn=conn,
                r=redis_client,
                model_name=settings.model_name,
            )
            return result

    return _retrieve


# --- Default production factory ----------------------------------------------


def default_runtime_factory(
    settings: Settings,
) -> contextlib.AbstractAsyncContextManager[AgentRuntime]:
    """Return the production runtime factory."""
    return _default_runtime_context(settings)


@contextlib.asynccontextmanager
async def _default_runtime_context(
    settings: Settings,
) -> AsyncIterator[AgentRuntime]:
    """Enter the production runtime.

    Order matters:

    1. Fail-closed configuration check for MCP.
    2. Postgres saver (checkpointer must be ready before the graph
       compiles).
    3. pgvector connection pool + Redis client for W7D3 retrieval.
    4. MCP transport + ``ClientSession``.
    5. Three async Anthropic clients (retrieval / api / synthesis).
    6. One *sync* Anthropic client for the W7D3 retrieval callable.
    7. Instructor wrapper on the synthesis async client only.
    8. Compile the graph over the live saver.
    """
    # Fail-closed BEFORE opening any network resource.
    _require_mcp_configuration(settings)

    # Late imports so ``import expense_agent_svc.app`` does not pull in
    # anthropic / mcp / langgraph-checkpoint-postgres at process import.
    import instructor as _instructor
    import redis as _redis
    from anthropic import Anthropic, AsyncAnthropic
    from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver
    from mcp import ClientSession
    from mcp.client.sse import sse_client
    from psycopg_pool import ConnectionPool

    from .graph import NodeSet, build_expense_agent_graph
    from .nodes.api import make_api_agent
    from .nodes.retrieval import make_retrieval_agent
    from .nodes.synthesis import make_synthesis_agent

    ready: dict[str, bool] = {
        "postgres_checkpointer": False,
        "rag_pool": False,
        "redis": False,
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

        # --- 2. pgvector pool + Redis (owned by the exit stack) --------
        # psycopg_pool.ConnectionPool.open() blocks briefly; we run it
        # off the event loop so the lifespan does not stall.
        pool = ConnectionPool(
            settings.rag_postgres_url,
            min_size=settings.rag_pool_min_size,
            max_size=settings.rag_pool_max_size,
            open=False,
        )
        await asyncio.to_thread(pool.open)
        stack.callback(pool.close)
        ready["rag_pool"] = True

        redis_client = _redis.Redis.from_url(settings.redis_url)
        stack.callback(redis_client.close)
        ready["redis"] = True

        # --- 3. MCP SSE transport + session ----------------------------
        bearer = settings.mcp_bearer_jwt.get_secret_value()
        mcp_headers = {"Authorization": f"Bearer {bearer}"}
        read_stream, write_stream, *_ = await stack.enter_async_context(
            sse_client(settings.mcp_sse_url, headers=mcp_headers)
        )
        session = await stack.enter_async_context(ClientSession(read_stream, write_stream))
        await session.initialize()
        ready["mcp_session"] = True

        # --- 4. Anthropic clients per worker ---------------------------
        api_key_value = settings.anthropic_api_key.get_secret_value() or None
        base_url = settings.anthropic_base_url or None

        def _async_client(role: str) -> AsyncAnthropic:
            return AsyncAnthropic(
                api_key=api_key_value,
                base_url=base_url,
                default_headers=anthropic_default_headers(role),
            )

        retrieval_client = _async_client(X_AGENT_RETRIEVAL)
        api_client = _async_client(X_AGENT_API)
        synthesis_raw = _async_client(X_AGENT_SYNTHESIS)
        stack.push_async_callback(retrieval_client.close)
        stack.push_async_callback(api_client.close)
        stack.push_async_callback(synthesis_raw.close)

        # --- 5. Sync retrieval client (W7D3 is synchronous) -----------
        # W7D3's `retrieve_and_generate` accepts a synchronous
        # Anthropic client; passing an async one would silently
        # break W7D3 inside asyncio.to_thread. This synchronous
        # client is the retrieval worker's mouthpiece and rides
        # the same X-Agent header.
        retrieval_sync_client = Anthropic(
            api_key=api_key_value,
            base_url=base_url,
            default_headers=anthropic_default_headers(X_AGENT_RETRIEVAL),
        )
        stack.callback(retrieval_sync_client.close)

        # --- 6. Instructor wrapper on synthesis only ------------------
        synthesis_client = _instructor.from_anthropic(synthesis_raw)

        # --- 7. Retrieval callable ------------------------------------
        retrieve = make_retrieval_callable(
            pool=pool,
            redis_client=redis_client,
            retrieval_anthropic=retrieval_sync_client,
            settings=settings,
        )

        dependencies = AgentDependencies(
            settings=settings,
            mcp_session=cast(Any, session),
            anthropic=api_client,
            instructor=synthesis_client,
            retrieve=retrieve,
        )

        # --- 8. Compile the graph over the live saver ------------------
        api_model_invoke = make_anthropic_model_invoke(
            api_client=api_client,
            model_name=settings.model_name,
        )
        node_set = NodeSet(
            retrieval_agent=make_retrieval_agent(dependencies),
            api_agent=make_api_agent(
                dependencies,
                model_invoke=api_model_invoke,
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


# --- Small helper for tests --------------------------------------------------


FakeRuntimeFactory = Callable[[Settings], contextlib.AbstractAsyncContextManager[AgentRuntime]]

__all__ = [
    "X_AGENT_API",
    "X_AGENT_RETRIEVAL",
    "X_AGENT_SYNTHESIS",
    "AgentRuntime",
    "FakeRuntimeFactory",
    "RuntimeConfigurationError",
    "RuntimeFactory",
    "anthropic_default_headers",
    "default_runtime_factory",
    "make_anthropic_model_invoke",
    "make_retrieval_callable",
]
