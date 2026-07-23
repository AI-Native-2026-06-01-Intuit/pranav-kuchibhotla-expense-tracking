"""FastAPI application factory + lifespan + /v1/chat/stream route.

Nothing here constructs an Anthropic / MCP / Postgres client at module
import — the ``import expense_agent_svc.app`` guardrail test proves it.
Concrete resources are built inside the FastAPI lifespan via a
:class:`~expense_agent_svc.runtime.RuntimeFactory` callable that tests
can override.

Surface:

* ``GET /healthz`` — lightweight liveness. No DB/MCP/LLM call.
* ``GET /readyz`` — readiness gated by lifespan initialisation.
* ``POST /v1/chat/stream`` — request-scoped ``BudgetGuard`` + LangGraph
  ``astream_events(v2)`` bridged through AI SDK v4 data-stream frames.

Neither endpoint leaks the DSN, bearer JWT, or Anthropic API key. The
streaming route generates an opaque ``request_id`` (never a UUID v4 —
those are reserved for deterministic UUID v5 idempotency keys inside
the API node) and returns it, plus the resolved ``thread_id``, in
response headers.
"""

from __future__ import annotations

import logging
import secrets
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import TYPE_CHECKING, Annotated, Any, cast

from fastapi import FastAPI, Request, status
from fastapi.responses import JSONResponse, StreamingResponse
from pydantic import BaseModel, ConfigDict, Field, field_validator

from .budgets import BudgetGuard
from .dependencies import RequestContext, register_request, release_request
from .settings import Settings, get_settings
from .sse import error_frame_for, event_stream

if TYPE_CHECKING:
    from .runtime import AgentRuntime, RuntimeFactory


_SERVICE_NAME = "expense-agent-svc"
_ALLOWED_TENANTS = frozenset({"tenant-a", "tenant-b", "tenant-c"})

_log = logging.getLogger("expense_agent_svc.app")


# --- Request model ------------------------------------------------------------


class ChatRequest(BaseModel):
    """Incoming payload for :func:`POST /v1/chat/stream`.

    ``extra="forbid"`` matches the W7D3/W7D4 convention — an unknown
    field is a hard schema error, not a silent drop.
    """

    model_config = ConfigDict(extra="forbid")

    question: Annotated[str, Field(min_length=2, max_length=2000)]
    tenant_id: str
    thread_id: str | None = Field(default=None, min_length=1, max_length=128)

    @field_validator("tenant_id")
    @classmethod
    def _validate_tenant(cls, v: str) -> str:
        # Mirror the synthetic-tenant allowlist used by W7D3 / W7D4 so
        # a mistyped tenant never reaches an MCP call.
        if v not in _ALLOWED_TENANTS:
            raise ValueError(f"unsupported tenant_id: {v!r}")
        return v


def _opaque_id(prefix: str) -> str:
    """Return a URL-safe opaque identifier (not a UUID v4).

    UUID v4 is reserved for interactive callers passing an
    idempotency_key to the MCP refund tool; the W7D5 agent service
    generates its own idempotency keys as UUID v5. Keeping
    ``uuid.uuid4`` out of production code lets a grep guardrail stay
    strict.
    """
    return f"{prefix}-{secrets.token_urlsafe(16)}"


# --- Application factory ------------------------------------------------------


def create_app(
    runtime_factory: RuntimeFactory | None = None,
    *,
    settings: Settings | None = None,
) -> FastAPI:
    """Return a fresh :class:`FastAPI` application."""
    if runtime_factory is None:
        # Late import so the anthropic / mcp packages are not pulled in
        # by ``import expense_agent_svc.app``.
        from .runtime import default_runtime_factory as _factory

        runtime_factory = _factory

    resolved_settings = settings if settings is not None else get_settings()

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        # Fresh dict on each lifespan so a repeated boot cannot see the
        # previous run's flags.
        app.state.ready = False
        app.state.runtime = None
        async with runtime_factory(resolved_settings) as runtime:
            app.state.runtime = runtime
            app.state.ready = True
            try:
                yield
            finally:
                app.state.ready = False
                app.state.runtime = None

    app = FastAPI(
        title=_SERVICE_NAME,
        version="0.1.0",
        lifespan=lifespan,
    )

    @app.get("/healthz")
    async def healthz() -> JSONResponse:
        # Deliberately does not touch runtime state — liveness must
        # answer even if a downstream (MCP, Postgres) is temporarily
        # unhealthy so the pod is not restarted for a transient blip.
        return JSONResponse({"status": "ok", "service": _SERVICE_NAME})

    @app.get("/readyz")
    async def readyz() -> JSONResponse:
        if not getattr(app.state, "ready", False):
            return JSONResponse(
                {"status": "not_ready", "service": _SERVICE_NAME},
                status_code=503,
            )
        runtime = getattr(app.state, "runtime", None)
        components = dict(runtime.ready) if runtime is not None else {}
        # ``components`` is a small dict of {name: bool} — no DSN,
        # token, or hostname is included.
        return JSONResponse({"status": "ready", "service": _SERVICE_NAME, "components": components})

    @app.post("/v1/chat/stream")
    async def chat_stream(payload: ChatRequest, request: Request) -> Any:
        # --- 1. Readiness gate ------------------------------------------
        if not getattr(app.state, "ready", False):
            return JSONResponse(
                {"error": "not_ready", "message": "Service is not ready."},
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                headers={"Retry-After": "5"},
            )
        runtime: AgentRuntime | None = getattr(app.state, "runtime", None)
        if runtime is None:
            return JSONResponse(
                {"error": "not_ready", "message": "Service is not ready."},
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                headers={"Retry-After": "5"},
            )

        # --- 2. Resolve thread_id (client-supplied or freshly minted) ---
        thread_id = payload.thread_id or _opaque_id("thread")

        # --- 3. Build the request-scoped context ------------------------
        request_id = _opaque_id("req")
        budget = BudgetGuard(ceiling_usd_e5=runtime.settings.request_budget_usd_e5)
        ctx = RequestContext(
            thread_id=thread_id,
            tenant_id=payload.tenant_id,
            budget=budget,
            request_id=request_id,
        )
        register_request(ctx)

        # --- 4. Assemble the initial checkpoint-safe state --------------
        initial_state: dict[str, object] = {
            "question": payload.question,
            "tenant_id": payload.tenant_id,
            "thread_id": thread_id,
            "request_id": request_id,
            "messages": [],
            "docs": [],
            "tool_results": {},
            "answer": None,
            "final_answer": None,
            "cost_usd_e5": 0,
            "visited_nodes": [],
            "errors": [],
        }

        # --- 5. Build the wrapper generator with cleanup ----------------
        async def _wrapped() -> AsyncIterator[bytes]:
            try:
                async for frame in event_stream(
                    graph=runtime.graph,
                    initial_state=initial_state,
                    thread_id=thread_id,
                ):
                    # Cooperative cancellation: if the client dropped the
                    # HTTP connection, stop pushing frames immediately.
                    if await request.is_disconnected():
                        return
                    yield frame
            except BaseException as exc:
                # ``event_stream`` already maps known errors to a
                # channel-3 frame. Anything reaching here is either an
                # asyncio.CancelledError (propagate) or an unexpected
                # error while composing frames — emit a safe generic
                # frame if the response is still open, then re-raise.
                if isinstance(exc, cast(type, __import__("asyncio").CancelledError)):
                    raise
                _log.exception("chat_stream wrapper error: internal_error")
                yield error_frame_for("internal_error")
                raise
            finally:
                # Always release the registry entry — success, error,
                # cancellation, or client disconnect all land here.
                release_request(request_id)

        # --- 6. Emit the streaming response -----------------------------
        headers = {
            # AI SDK v4 useChat data-stream transport signals.
            "X-Vercel-AI-Data-Stream": "v1",
            "Cache-Control": "no-cache",
            "X-Thread-Id": thread_id,
            "X-Request-Id": request_id,
        }
        return StreamingResponse(
            _wrapped(),
            media_type="text/plain; charset=utf-8",
            headers=headers,
        )

    return app


def run() -> None:
    """Console entry point — launch uvicorn with the production settings.

    Reads settings only when invoked, never at import.
    """
    # Late imports so ``import expense_agent_svc.app`` does not pull in
    # uvicorn's runtime graph.
    import uvicorn

    settings = get_settings()
    app = create_app(settings=settings)
    uvicorn.run(
        app,
        host=settings.host,
        port=settings.port,
        log_config=None,
    )


__all__ = ["ChatRequest", "create_app", "run"]
