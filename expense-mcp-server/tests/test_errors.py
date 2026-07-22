"""Central HTTP-to-McpError mapping tests."""

import pytest
from mcp import McpError

from expense_mcp_server.errors import (
    CODE_BAD_REQUEST,
    CODE_CONFLICT,
    CODE_FORBIDDEN,
    CODE_NOT_FOUND,
    CODE_RAG_TIMEOUT,
    CODE_TOO_MANY_REQUESTS,
    CODE_UPSTREAM_ERROR,
    map_http,
    rag_timeout,
)


@pytest.mark.parametrize(
    "status, expected_code",
    [
        (400, CODE_BAD_REQUEST),
        (401, CODE_FORBIDDEN),
        (403, CODE_FORBIDDEN),
        (404, CODE_NOT_FOUND),
        (409, CODE_CONFLICT),
        (429, CODE_TOO_MANY_REQUESTS),
        (500, CODE_UPSTREAM_ERROR),
        (502, CODE_UPSTREAM_ERROR),
        (503, CODE_UPSTREAM_ERROR),
        (418, CODE_UPSTREAM_ERROR),  # unexpected non-success collapses
    ],
)
def test_map_http_status_codes(status: int, expected_code: int) -> None:
    err = map_http(status, "body")
    assert isinstance(err, McpError)
    assert err.error.code == expected_code
    assert "body" in err.error.message


def test_map_http_truncates_large_bodies() -> None:
    long_body = "x" * 10_000
    err = map_http(500, long_body)
    # Bounded message keeps error tables from ballooning.
    assert len(err.error.message) < 400


def test_rag_timeout_uses_5040() -> None:
    err = rag_timeout("is a laptop deductible?")
    assert err.error.code == CODE_RAG_TIMEOUT
    assert "rag timeout" in err.error.message
