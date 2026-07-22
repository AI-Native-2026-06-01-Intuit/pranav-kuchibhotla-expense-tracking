# syntax=docker/dockerfile:1.7
# expense-mcp-server (W7D4) — SSE transport container.

FROM python:3.12-slim AS runtime

# Install uv from its official image; we keep the runtime slim.
COPY --from=ghcr.io/astral-sh/uv:0.4.18 /uv /usr/local/bin/uv

ENV UV_LINK_MODE=copy \
    UV_COMPILE_BYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    EXPENSE_MCP_HOST=0.0.0.0 \
    EXPENSE_MCP_PORT=8080

WORKDIR /app

# The uv path source lives at the sibling expense-ai/ package. Copy both
# projects so `uv sync` can resolve the local dependency.
COPY expense-ai /app/expense-ai
COPY expense-mcp-server /app/expense-mcp-server

WORKDIR /app/expense-mcp-server

RUN uv sync --frozen --no-dev

EXPOSE 8080

# Health check hits the /healthz route added by the SSE app; the route
# is exempt from bearer auth and returns a stable JSON body.
HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8080/healthz', timeout=3).read()" || exit 1

ENTRYPOINT ["uv", "run", "expense-mcp-server-sse"]
