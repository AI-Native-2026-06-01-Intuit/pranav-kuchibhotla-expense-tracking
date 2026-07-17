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
