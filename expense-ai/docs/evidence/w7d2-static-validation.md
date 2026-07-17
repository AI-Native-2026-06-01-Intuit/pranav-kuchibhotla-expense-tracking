# W7D2 static validation evidence

Local validation captured on 2026-07-17 against the `w7d2-implementation`
branch. All commands are run from `expense-ai/` unless noted.

## Environment

- `uv` project manager (no `pip install` was used).
- Docker Desktop running; `docker info` reports OK.
- `pgvector/pgvector:pg16` pre-pulled locally so Testcontainers does not
  race a first-time pull.
- Ryuk reaper disabled via `TESTCONTAINERS_RYUK_DISABLED=true` in
  `tests/conftest.py` because the local k3d proxy binds `:8080`; this is
  documented in the conftest and does not affect CI.

## Commands and outcomes

| Step | Command | Outcome |
| --- | --- | --- |
| Frozen sync | `uv sync --frozen` | 135 packages, no changes |
| Import sanity | `uv run python -c "import numpy, pandas, sentence_transformers, psycopg, pgvector, langsmith; print('w7d2 imports ok')"` | `w7d2 imports ok` |
| Ruff lint | `uv run ruff check` | All checks passed |
| Ruff format | `uv run ruff format --check` | 24 files already formatted |
| Mypy strict | `uv run mypy --strict src/ tests/` | Success: no issues in 24 source files |
| Pytest + coverage | `uv run pytest -v --cov=src --cov-fail-under=85` | **57 passed, 1 skipped**, total coverage **92.57%** |
| Corpus tests | `uv run pytest -v tests/test_corpus.py` | 9 passed |
| pgvector loader (Docker) | `uv run pytest -v tests/test_pgvector_loader.py` | 5 passed |
| Rag traceable (Docker) | `uv run pytest -v tests/test_rag_traceable.py` | 5 passed |
| RAGAS threshold | `uv run pytest -v tests/test_ragas_thresholds.py` | 2 passed, 1 skipped (missing `EXPENSE_AI_ANTHROPIC_API_KEY`) |
| Great Expectations (Docker) | `uv run pytest -v tests/test_great_expectations_suite.py` | 1 passed |
| LangSmith visibility (skip) | `EXPENSE_AI_ALLOW_EXTERNAL_SKIP=1 uv run python -m expense_ai.scripts.assert_langsmith_run_visible` | `SKIPPED: … missing env: ['LANGSMITH_API_KEY', 'EXPENSE_AI_PG_DSN']` |

## External tests that skipped locally

Skips are intentional and gated behind clear env checks:

- **`test_ragas_scores_meet_thresholds`** in
  `tests/test_ragas_thresholds.py` — skipped because
  `EXPENSE_AI_ANTHROPIC_API_KEY` is not set. The always-on
  `test_golden_set_shape` and `test_thresholds_match_assignment` still
  ran and passed, so the golden-set contract is enforced without
  requiring SaaS credentials.
- **`assert_langsmith_run_visible.py`** — skipped because
  `LANGSMITH_API_KEY` and `EXPENSE_AI_PG_DSN` are not set locally, with
  `EXPENSE_AI_ALLOW_EXTERNAL_SKIP=1` allowing an honest exit 0. The CI
  workflow provides both as secrets when available.

## Guardrail greps (repo root)

All expected empty:

```text
grep -RIn "lsv2_pt_"   . → (clean)
grep -RIn "sk-ant-"    . → (clean)
grep -RIn "LANGSMITH_API_KEY[[:space:]]*=" expense-ai/src ... .github/workflows/python-ci.yml → (clean)
grep -RIn "except:"    expense-ai/src expense-ai/tests → (clean)
grep -RIn "List[|Optional[|Union[" expense-ai/src expense-ai/tests → (clean)
grep -RIn "float64"    expense-ai/src expense-ai/tests → (clean)
grep -RIn "targetCPUUtilizationPercentage" .github expense-ai → (clean)
```

## Docker / Testcontainers status

- Docker Desktop reachable (`docker info` OK).
- `pgvector/pgvector:pg16` image pulled and cached.
- Three test files spin up Postgres containers:
  `test_pgvector_loader.py`, `test_rag_traceable.py`,
  `test_great_expectations_suite.py`. Each waits on the container using
  the shared `_pg_wait.wait_for_postgres` helper (real psycopg v3
  `SELECT 1`) rather than the default `psycopg2` wait strategy, since
  this project uses psycopg v3 only.
