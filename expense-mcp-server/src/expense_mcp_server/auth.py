"""Authentication + tenant context for the expense MCP server.

Two boundaries live here:

* **stdio** — the launcher process (Claude Desktop, ``uv run``) supplies
  the bearer JWT via ``EXPENSE_MCP_BEARER_JWT``; that token is forwarded
  verbatim to upstream Spring endpoints. Tool inputs still carry a
  ``tenant_id`` field because the rubric requires it in the schema.

* **SSE/HTTP** — the request boundary is
  :class:`expense_mcp_server.transports.sse.BearerAuthMiddleware`, which
  parses ``Authorization: Bearer <token>``, hands the token to a
  :class:`expense_mcp_server.jwt_verifier.JwtVerifier`, and only after a
  successful cryptographic verification (signature, ``exp``, ``aud``, and
  optional ``iss``) binds the resulting claims into the request context.
  There is no presence-only fallback — ``build_app()`` refuses to start
  when JWKS URL or audience is missing.

Tenant consistency: :func:`assert_tenant_matches` rejects tool
invocations whose ``tenant_id`` argument does not agree with the
tenant claim carried in the verified request context, so a caller
cannot use a tenant-a token to poke at tenant-b data even if the
schema accepted it.
"""

from __future__ import annotations

from contextvars import ContextVar
from dataclasses import dataclass

from mcp import McpError
from mcp.types import ErrorData

from .errors import CODE_FORBIDDEN


@dataclass(frozen=True, slots=True)
class RequestContext:
    """Per-request identity/tenant carried through the async call chain."""

    tenant_id: str | None
    bearer: str


_current: ContextVar[RequestContext | None] = ContextVar("expense_mcp_request", default=None)


def set_context(ctx: RequestContext) -> None:
    """Bind a :class:`RequestContext` to the current async task."""
    _current.set(ctx)


def clear_context() -> None:
    """Remove any bound request context (used by SSE middleware between calls)."""
    _current.set(None)


def current() -> RequestContext | None:
    """Return the currently bound request context, if any."""
    return _current.get()


def bearer_for_upstream(fallback: str) -> str:
    """Return the token that should be forwarded on outbound HTTP calls."""
    ctx = _current.get()
    if ctx is not None and ctx.bearer:
        return ctx.bearer
    return fallback


def _forbidden(reason: str) -> McpError:
    return McpError(ErrorData(code=CODE_FORBIDDEN, message=f"forbidden: {reason}"))


MCP_FORBIDDEN = _forbidden  # exported so tests can build the same shape


def parse_bearer(header_value: str | None) -> str:
    """Parse an ``Authorization: Bearer <token>`` header value.

    Raises :class:`McpError` (code 4030) if the header is missing,
    malformed, or contains an empty token.
    """
    if not header_value:
        raise _forbidden("missing bearer")
    parts = header_value.split(" ", 1)
    if len(parts) != 2 or parts[0].lower() != "bearer" or not parts[1].strip():
        raise _forbidden("malformed bearer")
    return parts[1].strip()


def assert_tenant_matches(arg_tenant: str) -> None:
    """Reject the call if the schema tenant conflicts with the request context tenant.

    A missing request-context tenant is treated as "not yet enforced"
    and passes; enforcement kicks in only when the SSE transport
    populated the context with a specific claim.
    """
    ctx = _current.get()
    if ctx is None or ctx.tenant_id is None:
        return
    if ctx.tenant_id != arg_tenant:
        raise _forbidden(f"tenant mismatch: token={ctx.tenant_id} arg={arg_tenant}")
