# syntax=docker/dockerfile:1.7
# expense-agent-svc (W7D5) — FastAPI + LangGraph supervisor image.
#
# Build context MUST be the repository root because this project has
# local path dependencies on ../expense-ai and ../expense-mcp-server:
#
#   docker build \
#     -f expense-agent-svc/Dockerfile \
#     -t expense-agent-svc:w7d5 \
#     .

FROM python:3.12-slim AS runtime

# Install uv from its official image; runtime stays slim.
COPY --from=ghcr.io/astral-sh/uv:0.4.18 /uv /usr/local/bin/uv

ENV UV_LINK_MODE=copy \
    UV_COMPILE_BYTECODE=1 \
    UV_CACHE_DIR=/tmp/uv-cache \
    PYTHONUNBUFFERED=1 \
    VIRTUAL_ENV=/app/expense-agent-svc/.venv \
    PATH=/app/expense-agent-svc/.venv/bin:/usr/local/bin:/usr/bin:/bin \
    EXPENSE_AGENT_HOST=0.0.0.0 \
    EXPENSE_AGENT_PORT=8080

WORKDIR /app

# Copy the three linked projects. The uv sources block in
# expense-agent-svc/pyproject.toml resolves expense-ai and
# expense-mcp-server as local editable path dependencies, so both must
# be present *before* `uv sync --frozen` runs.
COPY expense-ai /app/expense-ai
COPY expense-mcp-server /app/expense-mcp-server
COPY expense-agent-svc /app/expense-agent-svc

WORKDIR /app/expense-agent-svc

# Some Docker versions do not read Dockerfile-adjacent
# `Dockerfile.dockerignore` reliably, so we defensively clear any
# host-side ``.venv`` directories that may have slipped into the
# context. uv otherwise refuses to seed a fresh venv into a directory
# containing a foreign one.
RUN rm -rf /app/expense-ai/.venv \
           /app/expense-mcp-server/.venv \
           /app/expense-agent-svc/.venv \
           /app/expense-ai/__pycache__ \
           /app/expense-mcp-server/__pycache__

# --frozen: use the committed uv.lock exactly; --no-dev: skip test/lint
# packages. `uv sync` never regenerates the lockfile.
RUN uv sync --frozen --no-dev

# Drop to a non-root uid before exposing anything. 65532 is
# distroless-nonroot, which our sibling GitOps deployments already use;
# keeping the same uid means securityContext.runAsUser matches.
RUN chown -R 65532:65532 /app
USER 65532

EXPOSE 8080

# /healthz is the lightweight liveness path — it never touches
# Postgres/MCP/Anthropic (see app.py). Uses the Python stdlib so no
# curl/wget layer is added.
HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8080/healthz', timeout=3).read()" || exit 1

# expense-agent-svc console script -> expense_agent_svc.app:run
# (verified in pyproject.toml [project.scripts]). Call the venv-
# installed script directly so uv's cache is not required at runtime.
ENTRYPOINT ["/app/expense-agent-svc/.venv/bin/expense-agent-svc"]
