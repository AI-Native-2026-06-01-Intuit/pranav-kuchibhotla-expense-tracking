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
