"""FastMCP application object and lifespan wiring for the expense MCP server.

The lifespan owns one shared :class:`httpx.AsyncClient` per upstream so
tool calls do not pay a fresh TCP/TLS handshake per invocation, and so
connection pools clean up deterministically on shutdown. Tools reach
these shared resources via the :class:`Context` object FastMCP passes
them; see ``tools/orders.py`` for the pattern.
"""

from __future__ import annotations

from collections.abc import AsyncIterator, Callable
from contextlib import asynccontextmanager
from dataclasses import dataclass
from typing import cast

import httpx
from mcp.server.fastmcp import Context, FastMCP

from .settings import Settings, get_settings
from .telemetry import configure_logging, get_logger

_log = get_logger(__name__)


@dataclass(frozen=True, slots=True)
class Deps:
    """Container for shared resources exposed through the FastMCP lifespan.

    Tools should treat everything on this object as read-only for the
    lifetime of the process. Do not construct a new ``httpx.AsyncClient``
    per tool call — reuse ``orders_client`` / ``llm_client``.
    """

    settings: Settings
    orders_client: httpx.AsyncClient
    llm_client: httpx.AsyncClient
    # A callable rather than a direct reference so tests can inject a fake.
    rag_call: Callable[..., object]


def _default_rag_call() -> Callable[..., object]:
    """Resolve the real ``retrieve_and_generate`` from ``expense_ai`` at startup.

    Kept behind a factory so import failures happen at server-start time
    (with a structured stderr log line) rather than at module import.
    """
    from expense_ai.rag import retrieve_and_generate  # local import: heavy deps

    return cast(Callable[..., object], retrieve_and_generate)


@asynccontextmanager
async def lifespan(_server: FastMCP) -> AsyncIterator[Deps]:
    """Open shared HTTP clients on startup and close them on shutdown."""
    configure_logging()
    settings = get_settings()

    timeout = httpx.Timeout(settings.tool_timeout_default_s, connect=2.0)
    orders_client = httpx.AsyncClient(base_url=settings.orders_svc_url, timeout=timeout)
    llm_client = httpx.AsyncClient(base_url=settings.llm_proxy_url, timeout=timeout)

    try:
        rag_call = _default_rag_call()
    except Exception as exc:
        captured_error = str(exc)
        _log.warning(
            "rag_import_failed",
            error=captured_error,
            note="rag.retrieve_and_generate tool will error until deps are installed",
        )

        def _unavailable(*_args: object, **_kwargs: object) -> object:
            raise RuntimeError(f"expense_ai.retrieve_and_generate unavailable: {captured_error}")

        rag_call = _unavailable

    deps = Deps(
        settings=settings,
        orders_client=orders_client,
        llm_client=llm_client,
        rag_call=rag_call,
    )
    _log.info(
        "mcp_startup",
        orders_svc_url=settings.orders_svc_url,
        llm_proxy_url=settings.llm_proxy_url,
        langsmith_project=settings.langsmith_project,
    )
    try:
        yield deps
    finally:
        await orders_client.aclose()
        await llm_client.aclose()
        _log.info("mcp_shutdown")


mcp: FastMCP = FastMCP(
    name="expense-mcp-server",
    instructions=(
        "MCP surface for UptimeCrew expense. "
        "Use orders.get_order for tenant-scoped order reads, "
        "orders.create_refund for idempotent refund writes, "
        "llm.chat for bounded LLM chat, and "
        "rag.retrieve_and_generate for corpus-grounded answers."
    ),
    lifespan=lifespan,
)


def deps_from(ctx: Context) -> Deps:  # type: ignore[type-arg]
    """Return the lifespan :class:`Deps` bound to the current request."""
    lifespan_ctx = ctx.request_context.lifespan_context
    if not isinstance(lifespan_ctx, Deps):
        raise RuntimeError("lifespan context is not initialized")
    return lifespan_ctx


__all__ = ["Deps", "deps_from", "lifespan", "mcp"]
