"""Runtime dependency and per-request context surfaces.

Everything that is *not* JSON-serializable — MCP sessions, Anthropic
clients, Postgres pools, per-request ``BudgetGuard`` objects — lives in
this module and is passed to nodes at invocation time. Nothing here ever
enters :class:`~expense_agent_svc.state.AgentState`, so the
:class:`~langgraph.checkpoint.postgres.PostgresSaver` only ever writes
serializable data.

The LangGraph 1.2 API exposes ``context_schema`` on ``StateGraph`` and a
matching ``Runtime`` object at node time; that is the long-term
integration point for :class:`AgentDependencies`. However, ``Runtime``
requires the context to be a dataclass / TypedDict — it cannot carry an
open MCP ``ClientSession``. So the actual injection lives in a small
concurrency-safe registry keyed by a per-request id (the request stashes
a placeholder id in ``AgentState`` and nodes pull the live dependencies
back through :func:`get_request_context`). This keeps the graph state
serializable while still giving nodes typed access to their
collaborators.
"""

from __future__ import annotations

import secrets
import threading
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Protocol

if TYPE_CHECKING:
    from .settings import Settings


class BudgetGuardLike(Protocol):
    """Structural type covering the :class:`BudgetGuard` surface nodes call.

    The concrete implementation lives in :mod:`expense_agent_svc.budgets`
    (Phase 6). Using a Protocol here keeps this module import-cycle free
    and lets tests inject a fake without pulling in the real ceiling
    arithmetic.
    """

    @property
    def spent_usd_e5(self) -> int: ...

    @property
    def ceiling_usd_e5(self) -> int: ...

    def check_or_raise(self) -> None: ...

    def add_cost(self, cost_usd_e5: int) -> None: ...

    def record_usage(
        self,
        *,
        input_tokens: int,
        output_tokens: int,
        input_rate_usd_e5_per_million: int,
        output_rate_usd_e5_per_million: int,
    ) -> int: ...


class MCPSessionLike(Protocol):
    """Structural type for the subset of ``mcp.ClientSession`` we use.

    Kept as a Protocol so unit tests can drive the API and synthesis nodes
    with in-memory fakes and never touch the network transport.
    """

    async def list_tools(self, cursor: str | None = ...) -> object: ...

    async def call_tool(
        self,
        name: str,
        arguments: dict[str, object] | None = ...,
    ) -> object: ...


class AnthropicClientLike(Protocol):
    """Structural type for the injected Anthropic client used by the API node."""

    @property
    def messages(self) -> object: ...


class InstructorClientLike(Protocol):
    """Structural type for the injected Instructor client used by synthesis."""

    @property
    def messages(self) -> object: ...


class RetrievalCallable(Protocol):
    """Callable contract satisfied by :func:`expense_ai.rag.retrieve_and_generate`.

    Kept as a Protocol so the retrieval node can be exercised with a
    deterministic fake and never has to spin up pgvector + Redis.
    """

    def __call__(
        self,
        query_text: str,
        tenant_id: str,
        /,
    ) -> dict[str, object]: ...


@dataclass(frozen=True)
class AgentDependencies:
    """Long-lived, process-scoped dependencies shared across requests.

    The FastAPI lifespan constructs this exactly once. Nodes read
    ``settings`` and use ``mcp_session`` / ``anthropic`` / ``instructor``
    / ``retrieve`` through their Protocol interfaces. Nothing in here is
    ever checkpointed.
    """

    settings: Settings
    mcp_session: MCPSessionLike
    anthropic: AnthropicClientLike
    instructor: InstructorClientLike
    retrieve: RetrievalCallable


@dataclass
class RequestContext:
    """Per-request runtime context.

    Each incoming ``/v1/chat/stream`` request builds a fresh
    :class:`RequestContext` with its own :class:`BudgetGuard`; sharing
    one across requests would let one tenant's spend deny another. The
    thread/tenant identifiers echo the values also stored in
    :class:`AgentState`, but they are duplicated here so nodes never
    have to reach back into the checkpointed state to find their
    request identity.
    """

    thread_id: str
    tenant_id: str
    budget: BudgetGuardLike
    # An opaque id we hand to nodes through the state so they can find
    # this context in the registry. Nodes never see the underlying
    # dependencies dict directly. We use ``secrets.token_urlsafe`` (not
    # ``uuid.uuid4``) intentionally: idempotency keys in this service
    # are UUID v5 only, so keeping ``uuid4`` out of the whole package
    # makes the "no UUID v4 as idempotency key" guardrail a pure grep.
    request_id: str = field(default_factory=lambda: secrets.token_urlsafe(16))


class _RequestRegistry:
    """Thread-safe map from request id to :class:`RequestContext`.

    Node code fetches its per-request context through this registry.
    A module-global ``dict`` alone would race under concurrent requests;
    a lock keeps the register/unregister edges safe without pinning a
    ``BudgetGuard`` to a single event loop.
    """

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._by_id: dict[str, RequestContext] = {}

    def register(self, ctx: RequestContext) -> None:
        with self._lock:
            if ctx.request_id in self._by_id:
                raise KeyError(f"request_id {ctx.request_id!r} already registered")
            self._by_id[ctx.request_id] = ctx

    def get(self, request_id: str) -> RequestContext:
        with self._lock:
            ctx = self._by_id.get(request_id)
        if ctx is None:
            raise KeyError(f"unknown request_id {request_id!r}")
        return ctx

    def release(self, request_id: str) -> None:
        with self._lock:
            self._by_id.pop(request_id, None)

    def size(self) -> int:
        with self._lock:
            return len(self._by_id)


_REGISTRY = _RequestRegistry()


def register_request(ctx: RequestContext) -> None:
    """Register a per-request context so nodes can look it up."""
    _REGISTRY.register(ctx)


def get_request_context(request_id: str) -> RequestContext:
    """Return the per-request context for the given id.

    Raises ``KeyError`` if the request was never registered or has
    already been released — either is a programming error and should
    never happen on the happy path.
    """
    return _REGISTRY.get(request_id)


def release_request(request_id: str) -> None:
    """Release the per-request context (idempotent)."""
    _REGISTRY.release(request_id)


def _registry_size_for_tests() -> int:
    """Test helper — the registry itself is intentionally not exported."""
    return _REGISTRY.size()


class RequestContextUnavailable(RuntimeError):
    """A node was invoked with a state that carries no live request context.

    Raised when :func:`get_request_context_for_state` cannot resolve the
    state's ``request_id`` to a registered :class:`RequestContext` — for
    example because the request was cancelled and the registry entry
    was already released. The exception message stays generic on
    purpose (no request_id, no thread_id, no tenant) so it cannot leak
    identifiers into an SSE error frame.
    """


class RequestContextMismatch(RuntimeError):
    """Registered request context tenant/thread does not match the state.

    A resumed checkpoint might carry a stale ``request_id`` that maps
    to a *different* request. Refusing the run is safer than silently
    letting one request's tool spend against another request's budget.
    """


def get_request_context_for_state(state: object) -> RequestContext:
    """Resolve the live per-request context for a graph node's input state.

    ``state`` must expose a non-empty ``request_id`` string (a
    :class:`~collections.abc.Mapping` interface is sufficient — this
    accepts ``AgentState``, plain dicts, and any read-only mapping the
    graph plumbs through).

    The context's ``thread_id`` and ``tenant_id`` are checked against
    the state's values. A mismatch raises
    :class:`RequestContextMismatch` so a stale checkpoint pointing at a
    reused ``request_id`` cannot land on the wrong request's
    :class:`BudgetGuard`.
    """
    if not isinstance(state, dict):
        raise RequestContextUnavailable("state is not a mapping; cannot locate request_id")
    request_id = state.get("request_id")
    if not isinstance(request_id, str) or not request_id:
        raise RequestContextUnavailable("state carries no request_id")
    try:
        ctx = get_request_context(request_id)
    except KeyError as exc:
        # The exception text names only "the request could not be
        # continued" — never the request_id or any tenant/thread hint.
        raise RequestContextUnavailable("request context could not be resolved") from exc
    # Optional integrity check: if the state carries a tenant/thread we
    # match against the registered values. A mismatch is a hard failure.
    state_tenant = state.get("tenant_id")
    state_thread = state.get("thread_id")
    if isinstance(state_tenant, str) and state_tenant and state_tenant != ctx.tenant_id:
        raise RequestContextMismatch("state tenant does not match registered request")
    if isinstance(state_thread, str) and state_thread and state_thread != ctx.thread_id:
        raise RequestContextMismatch("state thread does not match registered request")
    return ctx
