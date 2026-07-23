"""FastAPI application factory + lifespan.

Nothing here constructs an Anthropic / MCP / Postgres client at module
import — the ``import expense_agent_svc.app`` guardrail test proves it.
Concrete resources are built inside :meth:`FastAPI.router.lifespan_context`
via a :class:`~expense_agent_svc.runtime.RuntimeFactory` callable that
tests can override.

The streaming route (``/v1/chat/stream``) is deferred to Phase 15; the
current surface is:

* ``GET /healthz`` — lightweight liveness. No DB/MCP/LLM call.
* ``GET /readyz`` — readiness gated by lifespan initialisation.

Neither endpoint leaks the DSN, bearer JWT, or Anthropic API key.
"""

from __future__ import annotations

from contextlib import asynccontextmanager
from typing import TYPE_CHECKING

from fastapi import FastAPI
from fastapi.responses import JSONResponse

from .settings import Settings, get_settings

if TYPE_CHECKING:
    from collections.abc import AsyncIterator

    from .runtime import RuntimeFactory


_SERVICE_NAME = "expense-agent-svc"


def create_app(
    runtime_factory: RuntimeFactory | None = None,
    *,
    settings: Settings | None = None,
) -> FastAPI:
    """Return a fresh :class:`FastAPI` application.

    ``runtime_factory`` — override for tests. Defaults to the production
    factory (:func:`~expense_agent_svc.runtime.default_runtime_factory`)
    which owns the ``AsyncExitStack`` for Postgres + MCP + Anthropic.
    """
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


__all__ = ["create_app", "run"]
