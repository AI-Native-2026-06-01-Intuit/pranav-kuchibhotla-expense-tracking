"""Central HTTP-to-McpError mapping.

Every tool that talks to an upstream Spring endpoint routes non-success
responses through :func:`map_http` so the wire-level error codes stay
consistent across ``orders``, ``llm``, and any future tool. The RAG
timeout path uses :func:`rag_timeout` which maps to a dedicated code.

Mapping (rubric-defined):

    400              -> 4001
    401 / 403        -> 4030
    404              -> 4040
    409              -> 4090
    429              -> 4290
    other 5xx        -> 5030
    unexpected non-2xx -> 5030
    RAG timeout      -> 5040
"""

from __future__ import annotations

from mcp import McpError
from mcp.types import ErrorData

# Public code table so tests can import it instead of hard-coding literals.
CODE_BAD_REQUEST = 4001
CODE_FORBIDDEN = 4030
CODE_NOT_FOUND = 4040
CODE_CONFLICT = 4090
CODE_TOO_MANY_REQUESTS = 4290
CODE_UPSTREAM_ERROR = 5030
CODE_RAG_TIMEOUT = 5040

# Bound the excerpt of upstream response bodies we surface, so a very
# large error page cannot balloon McpError.message.
_MAX_BODY_EXCERPT = 240


def _excerpt(body: str) -> str:
    if len(body) <= _MAX_BODY_EXCERPT:
        return body
    return body[: _MAX_BODY_EXCERPT - 1] + "…"


def _mcp(code: int, message: str, body: str) -> McpError:
    return McpError(ErrorData(code=code, message=f"{message}: {_excerpt(body)}"))


def map_http(status: int, body: str) -> McpError:
    """Turn an upstream HTTP status + body into a structured ``McpError``."""
    if status == 400:
        return _mcp(CODE_BAD_REQUEST, "bad request", body)
    if status in (401, 403):
        return _mcp(CODE_FORBIDDEN, "forbidden", body)
    if status == 404:
        return _mcp(CODE_NOT_FOUND, "not found", body)
    if status == 409:
        return _mcp(CODE_CONFLICT, "conflict", body)
    if status == 429:
        return _mcp(CODE_TOO_MANY_REQUESTS, "rate limited", body)
    if 500 <= status < 600:
        return _mcp(CODE_UPSTREAM_ERROR, "upstream error", body)
    # Any other unexpected non-success status collapses to a generic
    # upstream error so a novel code (e.g. 418) can never leak untyped.
    return _mcp(CODE_UPSTREAM_ERROR, f"unexpected status {status}", body)


def rag_timeout(question_excerpt: str) -> McpError:
    """Return the well-known error raised when the RAG tool exceeds its budget."""
    return _mcp(CODE_RAG_TIMEOUT, "rag timeout", question_excerpt)
