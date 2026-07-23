# expense-agent-svc

W7D5 multi-agent orchestration service for the UptimeCrew expense platform.

Three-node LangGraph 1.2 supervisor over:

- **retrieval_agent** — thin adapter over the W7D3 hybrid RAG pipeline
  (`expense-ai`).
- **api_agent** — dynamic MCP tool discovery + Anthropic tool-use loop
  against the W7D4 SSE surface (`expense-mcp-server`).
- **synthesis_agent** — Instructor-typed `FinalAnswer` with a
  deterministic empty-context refusal.

Durable checkpoints via `AsyncPostgresSaver`. Per-request `BudgetGuard`
(25 000 `cost_usd_e5` ceiling). Runtime `recursion_limit=25`. Per-node
deadlines (retrieval 3 s, API 5 s, synthesis 8 s). Deterministic
UUID v5 refund idempotency. `POST /v1/chat/stream` emits AI SDK v4
data-stream frames (`0:` text delta, `2:` typed FinalAnswer, `3:`
safe error slug).

See:

- [`RUNBOOK.md`](RUNBOOK.md) — on-call signals, troubleshooting, 30/60/90.
- [`PROMPT_JOURNAL.md`](PROMPT_JOURNAL.md) — real AI-driven decisions.
- [`docs/evidence/w7d5-static-validation.md`](docs/evidence/w7d5-static-validation.md) — final observed test / build / deployment-artefact results.

---

## Local prerequisites

- Python 3.12 (`.python-version` pins the exact minor).
- `uv` (astral). All Python commands below use `uv run`.
- Docker (for the local Postgres container and the image build).
- (Optional) `kubectl` + `kustomize` for local GitOps rendering.
- (Optional) `aws` CLI + a working profile for CloudFormation validation.

Copy `.env.example` to `.env` (or export the relevant variables) —
**never commit real values**. Placeholders only:

```
EXPENSE_AGENT_POSTGRES_URL=postgresql://postgres:postgres@localhost:5432/postgres
EXPENSE_AGENT_RAG_POSTGRES_URL=postgresql://postgres:postgres@localhost:55432/postgres
EXPENSE_AGENT_REDIS_URL=redis://localhost:6379/0
EXPENSE_AGENT_MCP_SSE_URL=http://127.0.0.1:8080/sse
EXPENSE_AGENT_MCP_BEARER_JWT=<signed JWT accepted by expense-mcp-server SSE>
EXPENSE_AGENT_ANTHROPIC_API_KEY=<sk-ant-... or llm-proxy token>
EXPENSE_AGENT_LANGSMITH_API_KEY=<optional>
EXPENSE_AGENT_LANGSMITH_PROJECT=expense-agent-svc-dev
```

Startup fails-closed when `EXPENSE_AGENT_MCP_BEARER_JWT` is empty —
the W7D4 SSE middleware verifies the JWT signature, expiry, and
audience on every request, and running without a token would produce
an infinite rejection loop.

---

## Local Postgres

```
docker run -d --name w7d5-postgres \
  -e POSTGRES_USER=postgres -e POSTGRES_PASSWORD=postgres -e POSTGRES_DB=postgres \
  -p 5432:5432 postgres:16
docker exec w7d5-postgres pg_isready -U postgres -d postgres
```

The tests in `tests/test_checkpointer_resume.py` connect through
`EXPENSE_AGENT_TEST_POSTGRES_URL` and skip loudly (never silently)
when the DSN is unreachable.

---

## Local commands

```
cd expense-agent-svc

uv sync --frozen

# Static gates
uv run ruff check
uv run ruff format --check
uv run mypy --strict src/ tests/ evals/

# Full suite (280 tests) with live Postgres integration
EXPENSE_AGENT_TEST_POSTGRES_URL=postgresql://postgres:postgres@localhost:5432/postgres \
  uv run pytest -v --cov=src --cov-fail-under=85

# Deterministic trajectory + cost gate (no external key required)
uv run python -m expense_agent_svc.scripts.eval --gate

# External RAGAS shape check — reports skipped/not_measured locally
# when the key is absent and the local-skip flag is set
EXPENSE_AGENT_ALLOW_EXTERNAL_EVAL_SKIP=1 \
  uv run python -m expense_agent_svc.scripts.eval --gate --external

# Build sdist + wheel
uv build
```

### Start the service

**Only start when every runtime dependency is configured** — a valid
signed MCP JWT, a reachable W7D4 SSE server, Anthropic credentials, a
reachable pgvector store, and a reachable Redis. Otherwise the
fail-closed startup will refuse.

```
uv run expense-agent-svc
```

Then:

```
curl -sSf http://127.0.0.1:8080/healthz
curl -sSf http://127.0.0.1:8080/readyz
```

`/healthz` never touches downstream state. `/readyz` returns 503 with
`Retry-After: 5` until the lifespan initialised the checkpointer,
pgvector pool, Redis client, MCP session, and compiled graph.

### Chat stream example

```
curl -N \
  -H 'Content-Type: application/json' \
  -H 'X-Thread-Id: <opaque-thread>' \
  --data '{
    "question": "What is the refund policy for order ord-synth-9001?",
    "tenant_id": "tenant-a"
  }' \
  http://127.0.0.1:8080/v1/chat/stream
```

Response headers include `X-Vercel-AI-Data-Stream: v1` and
`X-Thread-Id` (echoed or generated). The body carries `0:` text
deltas, one `2:` typed `FinalAnswer`, and — on error — a single `3:`
safe error slug. Never a raw exception, DSN, or JWT.

---

## Docker

Repo-root build context (path dependencies require it):

```
cd ..  # to repo root

docker build \
  -f expense-agent-svc/Dockerfile \
  -t expense-agent-svc:w7d5 \
  .

# Import smoke — never runs the default runtime (no MCP JWT here)
docker run --rm \
  --entrypoint python \
  expense-agent-svc:w7d5 \
  -c "from expense_agent_svc.app import create_app; print('agent image import ok')"

docker image inspect expense-agent-svc:w7d5
```

Runtime user 65532 (non-root), port 8080 exposed, HEALTHCHECK on
`/healthz` via the Python stdlib, no credentials baked into the image.

---

## Deployment prerequisites

The Argo Application and CI merge-to-main pipeline are **statically
valid** but not deployed. Before the first real production deploy:

1. Provision ECR repository
   `726695008378.dkr.ecr.us-east-1.amazonaws.com/expense-agent-svc`.
2. Configure repo variables `EXPENSE_AGENT_AWS_VALIDATION_ROLE_ARN`
   and `EXPENSE_AGENT_DEPLOY_ROLE_ARN` (OIDC roles).
3. Configure repo secrets `GITOPS_REPO_TOKEN`, `ANTHROPIC_API_KEY`,
   `LANGSMITH_API_KEY`.
4. Extend the config-repo `expense` AppProject `destinations:` to
   include `expense-svc`.
5. Bootstrap the config-repo path
   `expense-agent-svc/overlays/prod/` from the committed template
   (`scripts/bump_config_image.py --allow-bootstrap`).
6. Apply `argo-apps/expense-agent-svc.yaml` to the target Argo
   instance.
7. Deploy `cfn/agent-svc-budget.yaml` (with the customer-managed
   `DenyPolicyArn` supplied).

See [`RUNBOOK.md`](RUNBOOK.md) for the exact commands and the rollback
rehearsal procedure. **Rollback rehearsal is Pending real Argo CD
login and production deployment.**

---

## Honest infrastructure status

- No image has been pushed to ECR.
- The Argo Application has never been applied.
- The BudgetAction CloudFormation stack has never been deployed.
- The `expense-agent-svc-ci` workflow has never run against GitHub
  Actions.
- The local config repo (`~/Documents/pranav-kuchibhotla-expense-config`)
  has **not** been modified by this batch.
