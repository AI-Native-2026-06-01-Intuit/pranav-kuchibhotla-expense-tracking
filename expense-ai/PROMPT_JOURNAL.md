# PROMPT_JOURNAL.md

## W7D1 implementation prompt (single-prompt drive)

This sidecar was implemented from **one** combined Claude Code prompt for
Week 7 Day 1 (Python Sidecar — uv + Pydantic v2 + httpx + strict CI). No
separate interactive AI turns preceded it; the sections below are the two
scaffolding sub-briefs *inside* that one prompt, transcribed for the record.

Iteration after generation was purely mechanical: `ruff check`,
`ruff format --check`, `mypy --strict`, and `pytest --cov` were run in a
loop until every gate reported green. See the "AI authoring discipline"
section of [PYTHON.md](PYTHON.md) for the accept/reject calls.

## 1. Models scaffold requirements (from the prompt)

- Pydantic v2 with `ConfigDict(extra="forbid", frozen=True)` on every model.
- `populate_by_name=True` for models that use aliases.
- Java-facing camelCase aliases matching the wire contract:
  `tenant_id` <-> `tenantId`, `created_at` <-> `createdAt`,
  `correlation_id` <-> `correlationId`, `merchant_id` <-> `merchantId`,
  `model_id` <-> `modelId`.
- `Decimal` for money (`Merchant.amount` with `ge=0`, `max_digits=14`,
  `decimal_places=2`) and for `confidence` scores.
- At least one `@field_validator`:
  - `tenant_id` must start with `tenant-`.
  - `correlation_id` must start with `corr-`.
- At least one `@model_validator(mode="after")`:
  - `DeductionClassifyResult` with `confidence >= 0.90` must carry a
    rationale of at least 16 characters.
- No `typing.List` / `typing.Optional` / `typing.Union`; use PEP 585 /
  PEP 604 built-ins.
- No explicit `Any`. (Pydantic's synthesized `__init__` is the sole
  exception, suppressed per-class via `# type: ignore[explicit-any]`.)
- Three models: `Merchant`, `DeductionClassifyRequest`,
  `DeductionClassifyResult`.

## 2. Client scaffold requirements (from the prompt)

- Synchronous `LlmProxyClient` wrapping `httpx.Client`.
- Explicit `httpx.Timeout(settings.proxy_timeout_seconds)` — no relying on
  library defaults.
- Request envelope's `correlation_id` is propagated as the
  `x-correlation-id` header.
- Authorization is `Bearer {settings.proxy_api_key.get_secret_value()}`.
  This is the **only** place `get_secret_value()` is invoked.
- Structured JSON logging via `logging.Logger.info(json.dumps(...))`, with
  events `proxy.call.start`, `proxy.call.http_status`, `proxy.call.ok`, and
  `proxy.call.retryable_error`. Every line carries `event`,
  `correlation_id`, and `tenant_id`. The API key is never logged.
- Retries via tenacity `Retrying` with `stop_after_attempt` and
  `wait_exponential_jitter(initial=0.5, max=8.0)`.
- Retry only:
  - `httpx.TimeoutException`
  - `httpx.NetworkError`
  - `httpx.HTTPStatusError` where `status_code >= 500`
- **Never** retry 4xx.
- Retry decision lives in a named predicate function
  (`_is_retryable_exception`) so it is unit-testable and unambiguous.
- Client must expose `close()`, `__enter__`, and `__exit__`.
- No bare `except`; no explicit `Any`.

## 3. Iteration to green

Ran the exact quality gate documented in `PYTHON.md`:

```
uv sync --frozen
uv run ruff check
uv run ruff format --check
uv run mypy --strict src/ tests/
uv run pytest -v --cov=src --cov-fail-under=85
```

Concrete iterations required to reach green:

- `ruff format` — reformatted two files after initial write.
- `mypy --strict` — Pydantic 2's synthesized `__init__` forces `**data: Any`,
  which trips `disallow_any_explicit`. Fix: enable the `pydantic.mypy`
  plugin, add a targeted `# type: ignore[explicit-any]` on the four
  BaseModel/BaseSettings class definitions. No other `Any` was accepted.
- `pytest` — passed on first run once the code compiled clean.
