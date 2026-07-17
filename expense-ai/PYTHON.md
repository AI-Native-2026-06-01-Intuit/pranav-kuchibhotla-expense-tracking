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
