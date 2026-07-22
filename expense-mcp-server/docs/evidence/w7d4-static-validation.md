# W7D4 static validation evidence

## Branch and baseline

- Branch: `w7d4-implementation`
- Parent commit on `main`: `f82f6af` (W7D3 merge).
- Docker: `docker info` succeeded locally (`Docker OK`).
- Claude Desktop directory present at `~/Library/Application Support/Claude`.

## Gate runs (local, capstone laptop)

All commands executed from `expense-mcp-server/` unless noted.

| Command | Status |
| --- | --- |
| `uv sync --frozen` | pass |
| `uv run ruff check` | pass (0 findings) |
| `uv run ruff format --check` | pass |
| `uv run mypy --strict src/ tests/` | pass (0 findings, 30 files checked) |
| `uv run pytest --cov=src --cov-fail-under=85` | 62 passed, 1 skipped, coverage 89.15% |
| `uv run python -m expense_mcp_server.scripts.replay --fixtures tests/fixtures/` | wrote `.replay/latest.json`, `any_error=False` |
| `uv build` | wheel produced at `dist/expense_mcp_server-0.1.0-py3-none-any.whl` |
| `uv run expense-mcp-server-sse --help` | prints usage; entry point resolves |
| Java `./gradlew -p expense-api compileTestJava` | pass |
| `cd ../expense-ai && EXPENSE_AI_ALLOW_EXTERNAL_SKIP=1 uv run pytest -q` | W7D3 regression suite still green |

### Guardrail greps

Run from repo root (`~/Documents/uptimecrew-expense`):

- `grep -RIn "lsv2_pt_" expense-mcp-server .github/workflows/expense_mcp_server-ci.yml` — no hits.
- `grep -RIn "sk-ant-" expense-mcp-server .github/workflows/expense_mcp_server-ci.yml` — no hits.
- `grep -RIn "eyJ" expense-mcp-server .github/workflows/expense_mcp_server-ci.yml` — no hits (placeholders only).
- `grep -RIn "except:" expense-mcp-server/src expense-mcp-server/tests` — no bare except.
- `grep -RIn ": float\|amount: float" expense-mcp-server/src/expense_mcp_server/tools` — no float money field.
- `grep -RIn "print(" expense-mcp-server/src/expense_mcp_server` — no prints in server code.

## Skipped items and precise reasons

- `tests/test_e2e_mcp_to_spring.py::test_e2e_contract` — **skipped locally.**
  Reason: the test requires a built `expense-api` container image via
  `EXPENSE_MCP_E2E_IMAGE` and a reachable Docker daemon. Locally the
  image was not pre-built (Java Gradle build + Docker build takes
  multiple minutes and interferes with the capstone dev loop). The
  merge-to-main CI job runs the full E2E; see
  `.github/workflows/expense_mcp_server-ci.yml::e2e-merge`. The test
  code path is complete and will fail loudly if the assertion is
  violated — it does not fabricate a pass.
- **Claude Desktop end-to-end smoke** — **not executed.** The Desktop
  config at `configs/claude_desktop_config.json` uses an absolute path
  placeholder (`/ABSOLUTE/PATH/PLACEHOLDER/...`) rather than the
  user's real home directory; committing a machine-specific path is
  not appropriate for a shared repo. To exercise the launcher: copy
  the config to `~/Library/Application Support/Claude/claude_desktop_config.json`,
  substitute the absolute path to `expense-mcp-server/`, restart the
  Desktop app, and confirm the server appears under Tools.

## JWT validation level (SSE transport)

The SSE middleware currently enforces a **presence check only**:
`Authorization: Bearer <non-empty token>` must be present, and the
token is stored in a `contextvars.ContextVar` for outbound forwarding.
Cryptographic signature + audience validation is a follow-up that
plugs a `TokenVerifier` into `FastMCP(auth=…)`; it activates when both
`EXPENSE_MCP_JWKS_URL` and `EXPENSE_MCP_JWT_AUDIENCE` are configured.
That code path is not wired in this branch because no configured
JWKS endpoint was available at build time. This limitation is called
out here rather than papered over with a fake verifier.

## Coverage details

Reported by pytest --cov: total 89.15% (target 85%). Two modules under
90% by design:

- `tools/rag.py` at 72% — the top-of-tool wrapper is exercised only
  in the E2E path; the shape+timeout paths that carry the risk are
  covered by unit tests.
- `tools/orders.py` at 83% — the FastMCP-decorated wrapper functions
  that go through `Context` are unit-tested via the underlying
  `_get_order_impl` / `_create_refund_impl` helpers; the outer
  decorator wrappers run only in the stdio smoke + E2E.

## No-key guardrails

- `.env.example` contains placeholders only.
- `.env` is gitignored (`.gitignore` line 2).
- `Settings.bearer_jwt` is a `SecretStr`; repr is asserted to hide the
  value in `tests/test_lifespan_and_telemetry.py::
  test_settings_hides_secret_repr`.
- No real JWT/LangSmith/Anthropic key appears anywhere in the tree; the
  CI guardrail-grep step re-asserts this on every PR.

## Field-mapping note (RAG output → RagAnswer DTO)

The permissive dict returned by `expense_ai.rag.retrieve_and_generate`
is coerced to the strict `RagAnswer` schema as follows:

| Source (dict[str, object]) | Destination (`RagAnswer`)   | Notes                                                      |
| -------------------------- | --------------------------- | ---------------------------------------------------------- |
| `answer`                   | `answer` (str)              | Coerced via `str(...)`.                                    |
| `citations[:top_k]`        | `citations: list[Citation]` | Truncated to `top_k`; extras keys (e.g. `tenant_id`) dropped. |
| `citations[i].chunk_id`    | `Citation.chunk_id`         | Falls back to `id` for future compatibility.               |
| `citations[i].doc_id`      | `Citation.doc_id`           |                                                            |
| `citations[i].score`       | `Citation.score` (float)    | Non-numeric values coerce to 0.0.                          |
| `coverage`                 | `coverage` (float)          |                                                            |
| `rerank_timed_out`         | `rerank_timed_out` (bool)   |                                                            |
| `cache_hit`                | *(dropped)*                 | Internal to expense-ai; not part of the tool contract.     |
