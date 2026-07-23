# expense-ai (Python sidecar)

Python 3.12 sidecar that lives next to the Java expense service. It owns the
LLM-adjacent boundary: strict Pydantic v2 request/response models, an httpx
client to the internal LLM proxy, and a small CLI for local validation.

## What lives here

- `src/expense_ai/models.py` — Pydantic v2 boundary models (`Merchant`,
  `DeductionClassifyRequest`, `DeductionClassifyResult`). These are the
  Java/Python wire contract.
- `src/expense_ai/value_types.py` — frozen internal dataclasses
  (`ProxyCallKey`, `CorrelationContext`, `RetryPlan`). Immutable, hashable,
  slotted; use these for cache keys and correlation contexts.
- `src/expense_ai/settings.py` — pydantic-settings-based configuration.
  Secrets go through `SecretStr` and are only unwrapped inside `client.py`.
- `src/expense_ai/client.py` — synchronous `LlmProxyClient` around httpx
  with tenacity retries and structured JSON logging.
- `src/expense_ai/cli.py` — the single file allowed to `print`. It validates
  a request JSON on disk and echoes the aliased form on stdout.

## How to run

Everything runs through the [uv](https://docs.astral.sh/uv/) toolchain:

```bash
uv sync --frozen
uv run ruff check
uv run ruff format --check
uv run mypy --strict src/ tests/
uv run pytest -v --cov=src --cov-fail-under=85
```

CI (`.github/workflows/python-ci.yml`) runs the exact same commands. If a
step fails locally, it will fail in CI.

## Boundary contract

- Pydantic v2 with `ConfigDict(extra="forbid", frozen=True)` on every model
  — unknown fields are a validation error, not a silent drop.
- `populate_by_name=True` plus `Field(alias=...)` gives Python snake_case
  and Java camelCase side-by-side (`tenant_id` <-> `tenantId`, etc.).
- Money is `decimal.Decimal` with `max_digits=14, decimal_places=2`. Never
  `float`.
- `confidence` is also `Decimal` so strict typing does not silently allow
  float drift into a score field.
- Cross-field rules go through `@model_validator(mode="after")` — e.g.
  a `confidence >= 0.90` result must carry a rationale of at least 16
  characters.

## Secret discipline

- `EXPENSE_AI_PROXY_API_KEY` is stored as `SecretStr`. Its value is unwrapped
  in exactly one place: `LlmProxyClient._send`.
- `.env` is git-ignored. `.env.example` ships placeholders only
  (`replace-me`), so nothing sensitive is ever committed.
- Structured logs never carry the API key. Tests assert this — see
  `tests/test_client.py::test_happy_path_returns_result`.

## Client contract

- Explicit `httpx.Timeout(settings.proxy_timeout_seconds)`; no reliance on
  library defaults.
- Correlation ID from the request envelope flows into the
  `x-correlation-id` header.
- Retry with tenacity exponential jitter, but only for transient failures:
  `httpx.TimeoutException`, `httpx.NetworkError`, and 5xx
  `HTTPStatusError`. 4xx fails fast.
- Every log line is a JSON object with `event`, `correlation_id`, and
  `tenant_id`. Events: `proxy.call.start`, `proxy.call.http_status`,
  `proxy.call.ok`, `proxy.call.retryable_error`.

## AI authoring discipline

Accepted from the assistant on first draft:

- The Pydantic v2 boundary approach with `extra="forbid"` and camelCase
  aliases matching the Java JSON. This is the whole point of the sidecar:
  we own the wire contract in code, on both sides.

Rejected / rewritten:

- A first attempt suggested storing `proxy_api_key` as a plain `str`. That
  loses `repr()` protection and is trivially leakable via logs — replaced
  with `SecretStr` and a single `get_secret_value()` call inside the client.
- Suggested imports of `typing.List`, `typing.Optional`, `typing.Union`.
  Rejected in favor of Python 3.12 built-in generics (`list[X]`,
  `X | None`, `tuple[X, ...]`) plus a `disallow_any_explicit` mypy setting.
- Retrying 4xx responses "just in case." Rejected — a client error will
  never become non-client on retry, so retrying wastes quota and elongates
  the failure. The retry predicate is explicit about this.

## W7D2 additions — data tooling and RAG plumbing

W7D2 extends the sidecar into a small RAG data pipeline. New surface:

- `src/expense_ai/corpus.py` — pandas corpus loader (`load_corpus`) plus a
  MiniLM embedding pass (`embed_dataframe`). Embeddings are strict
  `np.float32` at 384 dimensions to match the pgvector column type.
- `sql/V001__doc_chunks.sql` — the `doc_chunks` schema with `vector(384)`,
  a `UNIQUE (doc_id, chunk_idx, model_version)` idempotency key, and an
  HNSW `vector_cosine_ops` index for the `<=>` cosine operator.
- `src/expense_ai/pgvector_loader.py` — psycopg v3 loader that calls
  `register_vector`, uses `executemany`, and upserts with
  `ON CONFLICT ... DO UPDATE` so re-running the loader against the same
  corpus keeps row count stable.
- `src/expense_ai/rag.py` — `@traceable` (`run_type="retriever"`) top-k
  retrieval. Requires `LANGSMITH_API_KEY` unless
  `EXPENSE_AI_ALLOW_EXTERNAL_SKIP=1`. Query is embedded once, cast to
  `np.float32`, filtered by `tenant_id` and `model_version`, ordered by
  `<=>`.
- `src/expense_ai/scripts/assert_langsmith_run_visible.py` — CLI check
  that a retrieval call surfaces as a `expense_ai.retrieve_chunks` run in
  LangSmith. Reads all credentials from env; exits 0 with a clear
  `SKIPPED` line when env vars are missing and skip is allowed.
- `tests/golden/expense_golden_50.jsonl` — 55 synthetic Q/A/context rows
  covering meals, mileage, home office, supplies, software, travel, phone,
  internet, plus at least three labeled failure-mode rows
  (`missing_context`, `junk_context`, `near_duplicate_context`).
- `tests/test_ragas_thresholds.py` — always-on shape gate on the golden
  set plus a real RAGAS `evaluate()` path that runs only when Anthropic
  credentials exist.
- `tests/test_great_expectations_suite.py` — 7-expectation GX suite over a
  Testcontainers Postgres+pgvector instance seeded with the real corpus.

### How to run W7D2 tests

```bash
uv sync --frozen
uv run pytest -v tests/test_corpus.py
uv run pytest -v tests/test_pgvector_loader.py           # Docker required
uv run pytest -v tests/test_rag_traceable.py             # Docker required
uv run pytest -v tests/test_ragas_thresholds.py
uv run pytest -v tests/test_great_expectations_suite.py  # Docker required
EXPENSE_AI_ALLOW_EXTERNAL_SKIP=1 uv run python -m expense_ai.scripts.assert_langsmith_run_visible
```

### External checks — honest skip discipline

The RAGAS `evaluate()` and LangSmith visibility paths need real SaaS
credentials. Rather than mock them (which would make the check
misleading), they honestly skip when env vars are missing:

- `test_ragas_scores_meet_thresholds` calls `pytest.skip()` if
  `EXPENSE_AI_ANTHROPIC_API_KEY` is unset.
- `assert_langsmith_run_visible.py` prints a `SKIPPED:` line and exits 0
  when `LANGSMITH_API_KEY`/`EXPENSE_AI_PG_DSN` are unset **and**
  `EXPENSE_AI_ALLOW_EXTERNAL_SKIP=1` — so CI without secrets is still
  green but never silently green.

The always-on `test_golden_set_shape` and `test_thresholds_match_assignment`
gate the golden set contract independently of any SaaS.

### AI authoring discipline — W7D2

Accepted from the first draft:

- The pandas corpus loader shape: `read_json`/`read_parquet` dispatch,
  deduplication on `(doc_id, chunk_idx)`, length filtering in
  `[1, 8000]`, `reset_index(drop=True)`.
- Matching pgvector's HNSW `vector_cosine_ops` opclass to the `<=>`
  cosine query operator, with `m = 16, ef_construction = 64`. This is
  the only combination that lets the ANN index actually serve the
  retrieval query.
- Using `pgvector.psycopg.register_vector(conn)` before both writes
  (loader) and reads (retrieval).

Rejected or corrected:

- Initial embeddings came back as `np.float64` (numpy default). Rejected —
  pgvector's `vector` column is 4-byte floats; keeping `float64` doubles
  memory and forces a conversion round-trip. Fixed with
  `np.asarray(..., dtype=np.float32)` at the boundary and per-row dtype
  assertions.
- A first pass skipped `register_vector(conn)` because inserts "seemed to
  work." Rejected — silent `TEXT` binding of embeddings would still
  insert but break vector arithmetic and index use. Now called before
  every cursor that touches the `embedding` column.
- Inline `Client(api_key="lsv2_...")` in the LangSmith script. Rejected —
  keys must come from env. `Client()` with no args reads
  `LANGSMITH_API_KEY` from environment; the script never sees the raw
  string.
- Retrieval SQL missing the `model_version` filter. Rejected — mixing
  results across model versions is a correctness bug (embedding spaces
  are not comparable). Test
  `test_model_version_filter_excludes_other_models` guards this.

## W7D3 — RAG 2.0 additions

W7D3 turns the W7D2 dense-only retrieval into a production-shaped hybrid
pipeline.

### New modules

- `sql/V002__rag2_metadata_and_partial_indexes.sql` — `chunk_metadata`
  jsonb, `content_hash` text, generated `chunk_tsv` tsvector, GIN
  `jsonb_path_ops` index for `@>` containment, per-tenant partial HNSW
  indexes (`m = 24, ef_construction = 128`) on `tenant-a/b/c`, and a
  GIN index on `chunk_tsv`. Every index uses
  `CREATE INDEX CONCURRENTLY IF NOT EXISTS` and is therefore applied
  from tests via `tests/_schema.py::apply_v002` with autocommit.
- `src/expense_ai/chunker.py` — `RecursiveCharacterTextSplitter` at
  `chunk_size=900, overlap=150`, separators
  `["\n\n", "\n", ". ", " ", ""]`, and stable per-doc
  `chunk-{doc_id}-p{i}` IDs on every produced piece.
- `src/expense_ai/pgvector_loader.py` — extended with `RagChunkRow`,
  `content_hash_for_text`, `load_rag_rows`, and the `needs_embedding`
  pre-embed gate. W7D2 `load_rows` and its tests remain untouched.
- `src/expense_ai/hybrid.py` — `dense_topk_filtered` and
  `sparse_topk_fts` (both DB-side tenant + metadata filtered),
  rank-based `rrf_fuse` at `k_const=60`, and a `coverage` diagnostic.
  No score normalization — RRF uses ranks only.
- `src/expense_ai/rerank.py` — greedy MMR at `lambda=0.7`, BGE
  cross-encoder rerank (`BAAI/bge-reranker-base`, `max_length=256`) with
  a strict 300 ms `timeout-and-fallback` and a testable timeout counter.
- `src/expense_ai/cache.py` — Redis semantic cache keyed on
  `expense_ai:sem:{tenant_id}:e{epoch}:{hash}`, plus `get_epoch` /
  `bump_epoch` and defense-in-depth citation-tenant checks on read.
- `src/expense_ai/rag.py::retrieve_and_generate` — end-to-end entry
  point wiring embed -> cache lookup -> dense -> hybrid FTS + RRF ->
  MMR -> BGE rerank -> Anthropic client -> cache store. Each stage is
  toggleable via keyword args or `RAG_USE_HYBRID/MMR/RERANK/FILTER` env.
- `src/expense_ai/dags/rag_svc_ingest.py` — Airflow TaskFlow DAG
  (`expense_ai_ingest`, five tasks, `max_active_runs=1`, `retries=2`,
  `retry_delay=5m`). Importable without a scheduler or credentials.

### New tests

- `tests/test_chunker.py` — chunk length bounds, stability, and
  per-doc namespacing.
- `tests/test_pgvector_rag_rows.py` — metadata containment via `@>` and
  the `needs_embedding` content-hash gate.
- `tests/test_hybrid_rrf.py` — hybrid retrieval on a Testcontainers
  pgvector DB, RRF rank accumulation, coverage bounds.
- `tests/test_rerank.py` — MMR order at `lambda=1.0` and diversity at
  `lambda=0.0`, BGE rerank order lift with an injected reranker, and
  the timeout-fallback path (no real BGE download in unit tests).
- `tests/test_semantic_cache.py` — near-duplicate cache hit, cross-tenant
  miss, `bump_epoch` invalidation, and defense-in-depth citation check.
- `tests/test_retrieve_and_generate.py` — cache hit skips Anthropic,
  citations include `tenant_id`, feature flags disable stages cleanly.
- `tests/test_tenant_isolation.py` — DB-side verification of tenant
  scoping across dense, sparse, and metadata-filtered paths.
- `tests/test_airflow_dag_import.py` — DAG import + retry config.
- `tests/test_ragas_gate.py` — 15-row RAGAS subset (see amendment) with
  a `>= 0.85` faithfulness gate and honest external skips.

### How to run W7D3 tests

```bash
uv sync --frozen
uv run pytest -v tests/test_chunker.py
uv run pytest -v tests/test_hybrid_rrf.py
uv run pytest -v tests/test_rerank.py
uv run pytest -v tests/test_semantic_cache.py
uv run pytest -v tests/test_tenant_isolation.py
uv run pytest -v tests/test_pgvector_rag_rows.py
uv run pytest -v tests/test_retrieve_and_generate.py
uv run pytest -v tests/test_airflow_dag_import.py
uv run pytest -v tests/test_ragas_gate.py -rs
uv run python -c "from expense_ai.dags.rag_svc_ingest import expense_ai_ingest_dag; print(expense_ai_ingest_dag.dag_id)"
```

### AI authoring discipline — W7D3

Accepted from the first draft:

- **RRF as rank-based fusion** at `k_const=60`. Ranks — not normalized
  scores — are the fusion signal. Two different retrievers produce
  incomparable score distributions; averaging them is the classic
  hybrid-retrieval trap.
- **Per-tenant partial HNSW indexes** (`WHERE tenant_id = 'tenant-x'`)
  paired with the `tenant_id = %s` predicate in the retrieval SQL.
  This is what makes tenant isolation checkable at the DB layer.
- **Timeout-and-fallback on the BGE reranker** at 300 ms. On timeout we
  return the pre-rerank order and bump a counter; the caller can page
  on excessive fallbacks.
- **Tenant + epoch in the cache key** plus a re-check of every cached
  citation's `tenant_id`. Defense in depth: a mis-scoped write cannot
  leak into another tenant's read path.

Rejected or corrected:

- A `0.5 * cosine + 0.5 * ts_rank` blend for hybrid fusion. Rejected —
  the two scales are not comparable, and this is exactly the failure
  mode RRF avoids. `hybrid.py` contains no `normalize_score` /
  `minmax_scale` helper; a `grep` guard in local validation enforces it.
- BGE reranker with no timeout. Rejected — a slow reranker turns into
  a latency incident. Now bounded by `RERANK_TIMEOUT_MS = 300`.
- Cache key omitting `tenant_id` "because the vector already differs
  across tenants." Rejected — the vector may not differ (near-duplicate
  content across tenants), and any collision would leak across tenant
  boundaries. Key includes tenant + epoch.
- HyDE / query rewriting as part of the pipeline. Rejected — the
  lesson explicitly excludes it today; adding it would be scope creep
  and would confound the ablation report.
- Fabricating RAGAS scores when the shared Anthropic workspace is
  capped. Rejected — the report table labels cells as
  `not executed locally` or `expected (assignment target)`; the gate
  test raises `SystemExit` for real failures and `pytest.skip`s for
  missing/capped credentials.
- Using the full 50-row golden set for every RAGAS iteration. Corrected
  after the 2026-07-20 cohort amendment — the eval now runs on a
  15-row deterministic subset (`tests/test_ragas_gate.py::
  _deterministic_subset`), with the 50-row shape gate preserved.

---

## W7D4 — MCP publishing surface

W7D4 adds a **sibling** uv project (`expense-mcp-server/`) that
publishes the Spring REST endpoints and the W7D3 in-process RAG
pipeline behind one FastMCP server. `expense-ai` stays unchanged; the
MCP project depends on it via `[tool.uv.sources]` path dependency.

### Four tools + one resource

| Surface                       | Purpose                                                                 |
| ----------------------------- | ----------------------------------------------------------------------- |
| `orders.get_order`            | Tenant-scoped read against `GET /api/v1/orders/{id}` on `expense-api`.  |
| `orders.create_refund`        | Idempotent write against `POST /api/v1/orders/{id}/refunds` with UUID v4. |
| `llm.chat`                    | Bounded chat proxy call; 429s map to MCP code 4290.                     |
| `rag.retrieve_and_generate`   | Calls `expense_ai.rag.retrieve_and_generate` in-process (asyncio.to_thread + wait_for). |
| `expense://catalogue`         | Read-only server + tool catalogue with tenant list and corpus stats.    |

### Contract highlights

- **Pydantic v2 with `extra="forbid"`** on every input; JSON schemas
  expose `additionalProperties: false` and unit tests assert it.
- **Decimal everywhere for money**; refund amounts travel on the wire
  as JSON strings (`"amount": "10.00"`) so no parser can silently widen
  to float.
- **UUID v4 idempotency keys** for `orders.create_refund` are validated
  in the schema and echoed into both the JSON body and the
  `Idempotency-Key` HTTP header. The Spring side enforces
  `(order_id, idempotency_key)` uniqueness at the storage layer, so a
  repeat call returns the same `refund_id` and never debits twice.
- **JWT forwarding + cryptographic verification.** stdio uses
  `EXPENSE_MCP_BEARER_JWT` from the process environment. SSE verifies
  incoming bearers cryptographically at the Starlette middleware
  boundary: `JwtVerifier` fetches a JWKS document from
  `EXPENSE_MCP_JWKS_URL` (bounded TTL, PyJWKClient), rejects `alg=none`
  and any algorithm outside an RS256/ES256 allow-list, and calls
  `jwt.decode` with an explicit `require=["exp","aud"]` plus signature,
  audience, and optional issuer (`EXPENSE_MCP_JWT_ISSUER`) checks. Only
  after verification succeeds does the middleware bind the verified
  tenant claim into the request `ContextVar`. Missing config causes
  `build_app()` to raise — there is no presence-only fallback. Every
  rejection returns the same externally-visible forbidden response so
  a caller cannot oracle which check failed.
- **Central HTTP → McpError mapping** lives in `errors.py::map_http`.
  Every HTTP status has one canonical code (400→4001, 401/403→4030,
  404→4040, 409→4090, 429→4290, 5xx→5030, RAG timeout→5040), covered
  by parametrized unit tests.
- **stderr-only logging.** stdlib logging and `structlog.JSONRenderer`
  both write to `sys.stderr`; `stdout` is reserved for JSON-RPC frames.
  A subprocess smoke test drives 100 `tools/list` calls and asserts no
  stray stdout text.
- **CI split**: the PR-tier job runs uv sync, ruff, mypy strict, unit
  tests, description-quality gate, stdio subprocess smoke, SSE auth
  tests, fixture replay, coverage ≥85, wheel build, and guardrail
  greps. The merge-to-main job builds an `expense-api` Docker image
  and runs the Testcontainers E2E that asserts the same idempotency
  key returns the same `refund_id`.

### Prerequisite gap and how it was closed

The W7D4 rubric assumes a W3D1 `expense-orders` service. This
capstone repo does not ship one, so the smallest possible synthetic
surface was added to the Java app: `SyntheticOrder`/`SyntheticRefund`
entities, a `V5__orders_refunds.sql` Flyway migration seeding
`ord-synth-9001` for `tenant-a`, and an `OrderController` with the two
routes the MCP adapter targets. The MCP server itself contains no
refund business logic — it only marshals DTOs and maps errors.

### How W7D5 consumes this

W7D5 discovers tools through the SSE transport's `tools/list` and
calls them through the same MCP surface Claude Desktop uses. The
`mcp.json` `forward_hook` block flags the adapter as the source of
truth so future clients do not bypass it and hit Spring directly.

### AI deviations (W7D4)

Deviations Claude Code applied (or corrected on user push-back)
during the W7D4 build:

- **Raw RAG output → bounded `RagAnswer` DTO.** The W7D3
  `retrieve_and_generate` returns `dict[str, object]` with internal
  keys like `cache_hit`; the MCP adapter drops those, truncates
  citations to `top_k`, and coerces scores to plain floats before
  handing the answer back to the client.
- **Float money → `Decimal` end-to-end.** Refund amounts on the wire
  travel as strings and parse back into `Decimal`; there is no `float`
  in the money path anywhere in the tool code.
- **Added required UUID v4 idempotency key.** The `orders.create_refund`
  schema enforces `version == 4` and forwards the same UUID in both
  body and header so upstream drift is caught immediately.
- **Logs moved from stdout to stderr.** Any `print` in server code
  would corrupt stdio JSON-RPC framing; the smoke test enforces this
  by driving 100 frames through a subprocess and asserting stdout
  cleanliness.
- **Centralized duplicated HTTP mappings.** Every tool goes through
  `errors.map_http`; the mapping table is defined once and covered by
  parametrized unit tests, so a novel status code cannot leak
  untranslated.
- **Corrected assumption that Claude Desktop launcher could `uvx`
  a path dependency.** The committed `configs/claude_desktop_config.json`
  uses `uv --directory <PATH> run …` so a path-based project (which
  cannot be published to a uvx registry) can still be launched by
  the Desktop app.

Deviations we considered but rejected:

- **Renaming the four tools to match the merchants domain that
  actually exists in this repo.** Rejected on user push-back: the
  W7D4 rubric requires the exact names `orders.get_order`,
  `orders.create_refund`, `llm.chat`, `rag.retrieve_and_generate`,
  and remapping them to merchant endpoints would break the E2E
  idempotency contract the rubric asserts.
- **Shipping SSE with presence-only bearer checking.** A post-merge
  review flagged that presence-only auth on a network transport was
  unacceptable. Corrected: `JwtVerifier` (using PyJWT + JWKS with a
  bounded cache and an RS256/ES256 allow-list) is now wired into the
  Starlette middleware, `build_app()` fails closed when JWKS or
  audience is missing, and `tests/test_sse_auth.py` exercises the
  reject paths with locally-generated RSA key pairs (no committed
  private key material). Evidence file updated accordingly.

## What W7D5 adds

W7D5 introduces a new sibling project, **`expense-agent-svc/`** — a
FastAPI + LangGraph 1.2 multi-agent orchestrator that consumes both
the W7D3 hybrid RAG (this package) and the W7D4 MCP surface.
`expense-ai` remains the source of truth for retrieval; W7D5 wraps it
in a thin adapter and orchestrates it alongside API and synthesis
workers.

The additions across the tree:

- **Three-node LangGraph supervisor** — `retrieval_agent`,
  `api_agent`, `synthesis_agent` in
  `expense-agent-svc/src/expense_agent_svc/nodes/`.
- **Supervisor parallel routing** — a `list[Send]` fan-out lets both
  workers run in the same super-step when a question spans policy +
  API; the reducers on `docs` (`operator.add`) and `tool_results`
  (custom merger) preserve both branches, and `synthesis_agent`
  executes exactly once at the fan-in join.
- **`AsyncPostgresSaver` checkpointer** owned by the FastAPI lifespan
  through an `AsyncExitStack`, matching the installed
  `langgraph-checkpoint-postgres 3.1.0` async-context-manager
  contract. Live restart/resume is proven by
  `tests/test_checkpointer_resume.py`.
- **Runtime recursion limit** — LangGraph 1.2 rejects
  `recursion_limit` on `compile()`; the value (25) lives on the
  invocation `configurable`. One central `invocation_config(thread_id)`
  helper is grep-enforced by an AST-based test walking every
  `.invoke/.ainvoke/.astream_events` call site in `src/`.
- **Per-request `BudgetGuard`** with a 25 000 `cost_usd_e5` ceiling.
  Money is integer only (per this codebase's rule); float/bool cost
  is rejected. Each `POST /v1/chat/stream` constructs its own guard,
  registered in the `RequestContext` registry — two concurrent
  requests never share one.
- **Per-node deadlines** — 3 s retrieval, 5 s API, 8 s synthesis.
  Each node is wrapped in an `asyncio.wait_for`-based decorator that
  returns a fresh sentinel copy on timeout and tags `deadline_exceeded`
  on the current LangSmith run.
- **W7D3 retrieval adapter** — `expense-agent-svc/src/expense_agent_svc/
  runtime.py::make_retrieval_callable` grabs one connection per call
  from a `psycopg_pool.ConnectionPool` opened against
  `EXPENSE_AGENT_RAG_POSTGRES_URL` (the pgvector store, distinct from
  the checkpointer DSN), passes it plus a Redis client and a
  synchronous retrieval-worker Anthropic client into
  `expense_ai.rag.retrieve_and_generate`. No W7D3 code changed.
- **W7D4 MCP dynamic discovery** — `nodes/api.py` calls
  `session.list_tools()` at runtime and translates the discovered
  `inputSchema` into the Anthropic tool-use shape. No hardcoded
  four-tool catalogue.
- **Deterministic UUID v5 refund idempotency** — `deterministic_
  idempotency_key(thread_id, tool_name, args)` seeds `uuid.uuid5`
  from a canonical args hash. Replay across checkpoint resume
  produces the same key, and the upstream ledger deduplicates.
  W7D4's `CreateRefundArgs.idempotency_key` was relaxed from
  UUID-v4-only to accept v4 (interactive) or v5 (agent-deterministic)
  in `feat(mcp): accept deterministic UUID5 idempotency keys`.
- **Instructor `FinalAnswer`** — `nodes/synthesis.py` uses
  `AsyncInstructor.messages.create_with_completion` (installed
  Instructor 1.15.4) with `response_model=FinalAnswer`,
  `max_retries=2`. The raw completion's `usage.input_tokens` /
  `output_tokens` feed real integer cost into `BudgetGuard.record_usage`
  at the configured per-M rates. Empty-context refusal short-circuits
  before the model call and returns `confidence < 0.4, citations=[]`.
- **AI SDK v4 stream bridge** — `sse.py` bridges
  `graph.astream_events(version="v2")` to the AI SDK v4 data-stream
  wire (`0:`, `2:`, `3:`) consumed by the new `AgentChatPanel` in
  `expense-web`. Channel 2 wraps `FinalAnswer` in a JSON array
  (`useChat.data`), channel 3 emits the safe slug (`useChat.error`).
  Exception reprs / DSNs / JWTs never appear on the wire.
- **Production RAGAS sampler** — `sampling.py::ProductionSampler`
  schedules 1 % (default) of grounded answers for background
  faithfulness/context recall/answer relevancy evaluation. Non-
  blocking (owns its `asyncio.Task` set, drained by `aclose()`),
  writes stable metadata (`ragas_faithfulness`, `ragas_context_recall`,
  `ragas_answer_relevancy`, `ragas_sampled=true`) via an injectable
  writer. Never fabricates a metric.
- **20-row trajectory gate** — `expense-agent-svc/evals/scenarios.jsonl`
  contains exactly 20 committed scenarios spanning docs-only,
  API-only, both, unknown-default and refusal across tenant-a/b/c.
  `scripts/eval.py --gate` walks them through deterministic fake
  nodes and asserts trajectory ≥ 0.70, answer ≥ 0.70, cost
  regression ≤ 15 % against a baseline labelled
  `"source": "deterministic_fixture"`. `--external` adds RAGAS
  faithfulness ≥ 0.85; missing key fails loudly in CI; local skip
  reports `status="skipped", faithfulness=null` — never a fabricated
  score.
- **Deployment shape** — repo-root Docker build with a non-root uid
  65532 image, `HEALTHCHECK` on `/healthz`; GitOps
  `expense-agent-svc/gitops/{base,overlays/prod}` matching the
  sibling `expense-api` conventions; Argo Application pointing at
  the actual config-repo remote at
  `expense-agent-svc/overlays/prod`; CloudFormation
  `agent-svc-budget.yaml` provisioning a $4 000/month
  `AWS::Budgets::Budget` + an `AWS::Budgets::BudgetsAction`
  (`ApprovalModel=AUTOMATIC`, `ActionType=APPLY_IAM_POLICY`) that
  attaches a DENY policy to `expense-agent-svc-role` at 100 % actual
  usage.

### Concrete AI-output deviations

Real deviations recorded during the eight-batch W7D5 implementation
(one commit each with more detail in
`expense-agent-svc/PROMPT_JOURNAL.md`):

1. **Rejected bare `docs`/`tool_results` state slots.** The lesson
   snippet drafted `docs: list[dict]` and `tool_results: dict` with
   no reducer. Two Sends to the same key in one super-step silently
   clobber. Replaced with `Annotated[…, operator.add]` and a custom
   `_merge_tool_results` reducer that preserves both parallel branches.
   Safety: fan-out data integrity is now a compile-time property.
2. **Rejected clients and `BudgetGuard` in `AgentState`.** The lesson
   snippet stored the MCP session and the Anthropic client on the
   state. Replaced with `dependencies.AgentDependencies` (process-scoped)
   + a `RequestContext` registry keyed by an opaque `request_id`;
   only serialisable scalars enter `AgentState`. Safety:
   `AsyncPostgresSaver` cannot accidentally serialise a Postgres
   connection, and two concurrent requests cannot share a
   `BudgetGuard`.
3. **Corrected `recursion_limit` from compile-time to invocation-time.**
   LangGraph 1.2.9's `StateGraph.compile()` no longer accepts the
   keyword. The single `invocation_config(thread_id)` helper carries
   `recursion_limit=25` on every graph invocation. An AST-based test
   walks `src/` and refuses any call site that omits it. Safety:
   the 25-step ceiling cannot be silently missing.
4. **Corrected `PostgresSaver` lifecycle to remain inside an async
   context manager.** The lesson snippet stored the saver as a
   long-lived attribute; installed `langgraph-checkpoint-postgres
   3.1.0` provides an `@asynccontextmanager` whose connection dies
   with the context. The FastAPI lifespan enters it inside an
   `AsyncExitStack` and compiles the graph *inside* that block.
   Safety: the checkpointer's Postgres connection is always closed
   on process shutdown.
5. **Rejected unsupported `MCP call_tool(headers=…)`.** The lesson
   snippet passed the idempotency key as an HTTP header via a
   `headers=` kwarg on `ClientSession.call_tool`. Installed
   `mcp 1.28.1` has no such parameter. The UUID5 goes into the tool
   `arguments` dict; the W7D4 server's `create_refund` tool already
   forwards it as the upstream HTTP `Idempotency-Key` header. Safety:
   the code compiles against the real MCP client, not a lesson artefact.
6. **Relaxed W7D4 UUID validation from v4-only to v4/v5.** The W7D4
   server rejected UUID v5, which the W7D5 deterministic idempotency
   contract requires. Rather than reshape the key into a v4-lookalike
   (which would leak the determinism into a v4 slot), we relaxed the
   accepted set to `{v4, v5}` — v1/v2/v3 still rejected. Safety: the
   two contracts are honestly compatible instead of paved-over.
7. **Rejected free-text synthesis.** The lesson snippet parsed
   citations back out of free-form model output with a regex.
   Replaced with Instructor `FinalAnswer` (`extra="forbid"`,
   `Citation.quote` bounded 10..240 chars, `confidence` in [0, 1]).
   Safety: an invented `doc_id` is a hard validation error, not a
   silent leak into the response.
8. **Rejected invented RAGAS values.** A missing evaluator key with
   the local-skip flag reports `status="skipped",
   faithfulness=null` — never a fabricated number.
   `evals/last_run.json` carries `"faithfulness": null` and
   `"source": "deterministic_fixture"`. CI never exports the local-
   skip flag. Safety: a green gate is measured, not confabulated.
9. **Corrected simple set-based trajectory matching to ordered
   parallel semantics.** The lesson snippet used `set(actual) ==
   set(expected)`, which would score a "synthesis first, then a
   worker" sequence as 1.0. Replaced with ordered semantics: every
   worker must appear before the terminal `synthesis_agent`; both
   workers on the both-branch may swap; a duplicate synthesis or a
   foreign node fails. Safety: supervisor regressions cannot pass
   the gate.
10. **Rejected direct deployment claims.** The lesson snippet's
    final report contained a "deployed and Synced/Healthy" block.
    Actual state: no `argocd login`, no `argocd app create`, no ECR
    repo, no image push, no CFN stack, no GitHub Actions run. The
    runbook's rollback rehearsal is `PENDING` with every field
    named; the evidence doc's checklist keeps those items
    unchecked. Safety: the audit trail matches reality.

Each deviation has a corresponding assertion in `expense-agent-svc/tests/`
so future edits that regress the choice fail loudly.
