"""SSE/HTTP transport entry point.

Bound to the ``expense-mcp-server-sse`` console script. Adds a Starlette
middleware in front of FastMCP's SSE app that:

* rejects requests missing an ``Authorization: Bearer <token>`` header
  with HTTP 401 and a JSON body carrying MCP error code 4030,
* parses the token and binds a :class:`RequestContext` for the rest of
  the request via the :mod:`expense_mcp_server.auth` context vars.

Cryptographic JWT validation (signature + audience) is a follow-up
that plugs a ``TokenVerifier`` into ``FastMCP(auth=...)`` when
``EXPENSE_MCP_JWKS_URL`` and ``EXPENSE_MCP_JWT_AUDIENCE`` are set. The
current implementation is a presence check only; the
``docs/evidence/w7d4-static-validation.md`` document records that
limitation honestly.
"""

from __future__ import annotations

import argparse
import json

import uvicorn
from mcp import McpError
from starlette.applications import Starlette
from starlette.middleware import Middleware
from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.requests import Request
from starlette.responses import JSONResponse, Response

from ..app import mcp
from ..auth import RequestContext, clear_context, parse_bearer, set_context
from ..errors import CODE_FORBIDDEN
from ..settings import get_settings
from ..telemetry import configure_logging, get_logger
from . import _registry  # noqa: F401 - side-effect: registers tools

_log = get_logger("expense_mcp_server.transports.sse")


def _forbidden_response(reason: str) -> JSONResponse:
    body = {"error": {"code": CODE_FORBIDDEN, "message": f"forbidden: {reason}"}}
    return JSONResponse(body, status_code=401)


class BearerAuthMiddleware(BaseHTTPMiddleware):
    """Enforce bearer-token presence and bind the request-scoped tenant/token.

    Health/actuator paths are allowed to pass through unauthenticated so
    a Kubernetes liveness probe does not need a token.
    """

    _PUBLIC_PATHS = ("/healthz", "/readyz")

    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        if request.url.path in self._PUBLIC_PATHS:
            return await call_next(request)

        auth_header = request.headers.get("authorization")
        try:
            token = parse_bearer(auth_header)
        except McpError as exc:
            reason = str(exc.error.message)
            _log.warning("sse.auth.rejected", reason=reason)
            return _forbidden_response(reason)

        # Tenant claim inspection would live here once JWKS validation is
        # wired. For presence-check mode we optionally read a client-
        # asserted ``X-Tenant-Id`` header (used by tests).
        asserted_tenant = request.headers.get("x-tenant-id")
        set_context(RequestContext(tenant_id=asserted_tenant, bearer=token))
        try:
            return await call_next(request)
        finally:
            clear_context()


async def _healthz(_request: Request) -> Response:
    return JSONResponse({"status": "ok", "server": "expense-mcp-server"})


def build_app() -> Starlette:
    """Construct the Starlette ASGI app that fronts FastMCP's SSE transport."""
    sse_app = mcp.sse_app()
    app = Starlette(
        debug=False,
        middleware=[Middleware(BearerAuthMiddleware)],
        routes=[
            *sse_app.routes,
        ],
    )
    # A minimal healthz so the Dockerfile HEALTHCHECK has a real endpoint
    # to hit — see also the middleware's public-path allowlist above.
    app.add_route("/healthz", _healthz)
    return app


def main() -> None:
    """Console entry point for the SSE transport."""
    parser = argparse.ArgumentParser(
        prog="expense-mcp-server-sse",
        description="HTTP/SSE MCP transport for the UptimeCrew expense surface.",
    )
    parser.add_argument("--host", default=None, help="Bind host (EXPENSE_MCP_HOST)")
    parser.add_argument("--port", type=int, default=None, help="Bind port (EXPENSE_MCP_PORT)")
    parser.add_argument(
        "--print-openapi",
        action="store_true",
        help="Print the resolved settings snapshot as JSON and exit.",
    )
    args = parser.parse_args()

    configure_logging()
    settings = get_settings()

    if args.print_openapi:
        # Small helper for the CI smoke; never touches the network.
        snapshot = {
            "host": args.host or settings.host,
            "port": args.port or settings.port,
            "sse_path": mcp.settings.sse_path,
            "message_path": mcp.settings.message_path,
        }
        # Cannot use ``print`` — write to stderr through the same JSON logger,
        # then also write the snapshot to stdout because the caller explicitly
        # requested a machine-readable dump.
        import sys

        sys.stdout.write(json.dumps(snapshot) + "\n")
        sys.stdout.flush()
        return

    app = build_app()
    _log.info(
        "sse.starting",
        host=args.host or settings.host,
        port=args.port or settings.port,
    )
    uvicorn.run(
        app,
        host=args.host or settings.host,
        port=args.port or settings.port,
        log_config=None,
    )


if __name__ == "__main__":
    main()
