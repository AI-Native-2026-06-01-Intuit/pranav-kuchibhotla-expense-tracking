"""SSE transport authentication tests.

The current SSE boundary enforces a presence check (bearer token must be
non-empty and well-formed). Cryptographic verification would slot into
FastMCP's ``TokenVerifier`` hook when JWKS + audience are configured;
the presence check is what these tests exercise.
"""

from mcp import McpError
from starlette.testclient import TestClient

from expense_mcp_server.auth import (
    RequestContext,
    assert_tenant_matches,
    clear_context,
    parse_bearer,
    set_context,
)
from expense_mcp_server.errors import CODE_FORBIDDEN
from expense_mcp_server.transports.sse import build_app


def test_missing_bearer_rejected_with_4030() -> None:
    app = build_app()
    with TestClient(app) as client:
        r = client.get("/sse")
    assert r.status_code == 401
    body = r.json()
    assert body["error"]["code"] == CODE_FORBIDDEN


def test_malformed_bearer_rejected_with_4030() -> None:
    app = build_app()
    with TestClient(app) as client:
        r = client.get("/sse", headers={"Authorization": "NotBearer abc"})
    assert r.status_code == 401
    assert r.json()["error"]["code"] == CODE_FORBIDDEN


def test_healthz_is_public() -> None:
    app = build_app()
    with TestClient(app) as client:
        r = client.get("/healthz")
    assert r.status_code == 200
    assert r.json()["status"] == "ok"


def test_parse_bearer_happy_path() -> None:
    assert parse_bearer("Bearer synthetic-test-token") == "synthetic-test-token"


def test_assert_tenant_matches_rejects_mismatch() -> None:
    set_context(RequestContext(tenant_id="tenant-a", bearer="synthetic"))
    try:
        # Same tenant is fine.
        assert_tenant_matches("tenant-a")
        # Mismatch raises.
        raised = False
        try:
            assert_tenant_matches("tenant-b")
        except McpError as exc:
            raised = True
            assert exc.error.code == CODE_FORBIDDEN
        assert raised
    finally:
        clear_context()


def test_assert_tenant_matches_noop_without_context() -> None:
    clear_context()
    # No context means the SSE middleware hasn't populated a claim yet,
    # so schema-provided tenant is accepted (stdio pass-through mode).
    assert_tenant_matches("tenant-a")
