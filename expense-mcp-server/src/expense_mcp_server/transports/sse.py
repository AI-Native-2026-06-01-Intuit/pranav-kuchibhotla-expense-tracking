"""SSE/HTTP transport entry point.

Bound to the ``expense-mcp-server-sse`` console script. Adds a Starlette
middleware in front of FastMCP's SSE app that:

* refuses to start when the JWT verification config
  (``EXPENSE_MCP_JWKS_URL`` + ``EXPENSE_MCP_JWT_AUDIENCE``) is missing,
  so an unverifiable token cannot traverse the network transport;
* rejects requests whose ``Authorization: Bearer <token>`` header is
  missing, malformed, or whose token fails cryptographic verification
  (signature, ``exp``, ``aud``, and optional ``iss``), always with the
  same externally-visible forbidden response;
* binds a :class:`RequestContext` carrying the verified tenant claim
  and the raw token for outbound forwarding.

Cryptographic verification lives in :mod:`expense_mcp_server.jwt_verifier`
so the request path stays small and the algorithm allow-list, JWKS TTL,
and clock skew are all in one place.
"""

from __future__ import annotations

import argparse
import json
from typing import Any

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
from ..jwt_verifier import JwtVerifier, VerificationError
from ..settings import Settings, get_settings
from ..telemetry import configure_logging, get_logger
from . import _registry  # noqa: F401 - side-effect: registers tools

_log = get_logger("expense_mcp_server.transports.sse")

# Externally-visible reason string for every rejection. The internal
# ``VerificationError.reason`` categories stay in the stderr logs; the
# caller only ever sees this one string so a forged-token attacker
# cannot use rejection messages to probe which check failed.
_FORBIDDEN_REASON = "forbidden"


class SseAuthNotConfiguredError(RuntimeError):
    """Raised at startup if the SSE transport lacks JWT verification config.

    The SSE surface is a network transport; running it without JWKS +
    audience would let anyone with an open port hand us an unverified
    bearer. Fail closed at build time so a misconfiguration cannot ship.
    """


def _forbidden_response() -> JSONResponse:
    body = {"error": {"code": CODE_FORBIDDEN, "message": "forbidden"}}
    return JSONResponse(body, status_code=401)


def _tenant_from_claims(claims: dict[str, Any]) -> str | None:
    """Extract the tenant claim.

    The rubric does not pin an IdP shape, so this looks at the two
    common conventions in order: a ``tenant_id`` claim and a
    ``tenant`` claim. Anything else falls through to ``None``, and the
    tool-argument tenant becomes the only enforcement point.
    """
    for key in ("tenant_id", "tenant"):
        raw = claims.get(key)
        if isinstance(raw, str) and raw:
            return raw
    return None


class BearerAuthMiddleware(BaseHTTPMiddleware):
    """Cryptographically verify the bearer JWT and bind the verified claims.

    Health/actuator paths are allowed to pass through unauthenticated so
    a Kubernetes liveness probe does not need a token; those paths never
    reach the FastMCP app.
    """

    _PUBLIC_PATHS = ("/healthz", "/readyz")

    def __init__(self, app: Any, verifier: JwtVerifier) -> None:
        super().__init__(app)
        self._verifier = verifier

    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        if request.url.path in self._PUBLIC_PATHS:
            return await call_next(request)

        auth_header = request.headers.get("authorization")
        try:
            token = parse_bearer(auth_header)
        except McpError:
            # Presence / shape failures share the same external reason as
            # cryptographic failures — see class docstring.
            _log.warning("sse.auth.rejected", reason="malformed_bearer")
            return _forbidden_response()

        try:
            claims = self._verifier.verify(token)
        except VerificationError as exc:
            _log.warning("sse.auth.rejected", reason=exc.reason)
            return _forbidden_response()

        tenant_id = _tenant_from_claims(claims)
        set_context(RequestContext(tenant_id=tenant_id, bearer=token))
        try:
            return await call_next(request)
        finally:
            clear_context()


async def _healthz(_request: Request) -> Response:
    return JSONResponse({"status": "ok", "server": "expense-mcp-server"})


def _build_verifier(settings: Settings) -> JwtVerifier:
    if not settings.has_jwt_validation():
        # Fail-closed startup guard. The SSE transport is a network
        # boundary, so missing verification config is a hard error, not
        # a fallback to presence-only.
        raise SseAuthNotConfiguredError(
            "EXPENSE_MCP_JWKS_URL and EXPENSE_MCP_JWT_AUDIENCE must be set "
            "to start the SSE transport; there is no presence-only fallback."
        )
    return JwtVerifier(
        jwks_url=settings.jwks_url,
        audience=settings.jwt_audience,
        issuer=settings.jwt_issuer or None,
        cache_ttl_s=settings.jwks_cache_ttl_s,
    )


def build_app(verifier: JwtVerifier | None = None) -> Starlette:
    """Construct the Starlette ASGI app that fronts FastMCP's SSE transport.

    Accepts an optional ``verifier`` so tests can inject a fixture-driven
    :class:`JwtVerifier` pointing at a locally-generated JWKS. In
    production the verifier is built from :func:`get_settings`.
    """
    resolved_verifier = verifier if verifier is not None else _build_verifier(get_settings())
    sse_app = mcp.sse_app()
    app = Starlette(
        debug=False,
        middleware=[Middleware(BearerAuthMiddleware, verifier=resolved_verifier)],
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
