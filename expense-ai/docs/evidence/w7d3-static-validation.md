# W7D3 static validation evidence

Recorded on branch `w7d3-implementation` before commits, on macOS
Darwin 25.5.0 with Docker Desktop running.

## Local environment status

- `docker info`: reachable (Docker OK).
- `w7d3-redis` container: running (`redis-cli ping` returns `PONG`).
- `w7d2-pgvector` container: running.
- Testcontainers Postgres `pgvector/pgvector:pg16`: pulls and starts on
  demand for each test module (session/module scoped fixtures reuse
  containers within a run).
- Testcontainers Redis `redis:7-alpine`: pulls and starts on demand for
  `test_semantic_cache.py` and `test_retrieve_and_generate.py`.

## Commands executed and outcomes

```
uv sync --frozen                          # OK (135 -> 217 packages after W7D3 deps)
uv run ruff check                         # All checks passed
uv run ruff format --check                # OK
uv run mypy --strict src/ tests/          # Success: no issues found in 35 source files
uv run pytest -v --cov=src --cov-fail-under=85
```

Full-suite pytest results are captured in the Phase 15 validation
transcript in the session log; the final counts and any skips are
included there.

## External RAGAS status

The 15-row RAGAS faithfulness gate
(`tests/test_ragas_gate.py::test_ragas_faithfulness_meets_gate`) is
marked `slow` and `external`. Locally it **skips** because the local
shell has no `EXPENSE_AI_ANTHROPIC_API_KEY` / `ANTHROPIC_API_KEY`. The
shape gates in the same file (`test_golden_set_min_size`,
`test_ragas_thresholds_constants`, `test_eval_subset_size_is_fifteen`,
`test_eval_subset_is_deterministic`, `test_eval_subset_row_shape`) run
unconditionally and pass.

CI is wired to secrets (`.github/workflows/python-ci.yml`) and will
execute the external gate when the cohort's shared workspace has
budget. See `docs/ragas/w7d3.md` for the corresponding score-table
policy (`not executed locally` / `expected (assignment target)`).

## Guardrail greps (pre-commit sanity)

```
grep -RIn "lsv2_pt_" .                                                # empty
grep -RIn "sk-ant-" .                                                 # empty
grep -RIn "except:" expense-ai/src expense-ai/tests                   # empty
grep -RIn "normalize.*score\|min[_-]max" expense-ai/src/expense_ai/hybrid.py  # empty
grep -RIn "CREATE INDEX [^C]" expense-ai/sql/V002__rag2_metadata_and_partial_indexes.sql  # empty
```

Every CREATE INDEX in V002 uses `CREATE INDEX CONCURRENTLY IF NOT EXISTS`
and the tests apply the migration with autocommit via
`tests/_schema.py::apply_v002`.
