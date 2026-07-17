# PROMPT_JOURNAL.md

## Honest framing

There was **one** Claude Code prompt for W7D1, not two separate interactive
turns. Rather than pretend otherwise, this journal reproduces the two
sub-sections of that single prompt that drove the models scaffold and the
client scaffold, and pastes the unedited files Claude produced in reply.
The full source of both files lives at
[`src/expense_ai/models.py`](src/expense_ai/models.py) and
[`src/expense_ai/client.py`](src/expense_ai/client.py); the excerpts below
are the exact contents committed on first generation (and unchanged since,
apart from a `ruff format` pass and four `# type: ignore[explicit-any]`
suppressions noted at the bottom).

Nothing sensitive was in either prompt or reply: the API key placeholder
throughout is `replace-me` (env) or `test-key-do-not-log` (tests).

---

## Exchange 1 — Models

### Prompt (verbatim, Phase 2 of the W7D1 brief)

> Phase 2 — implement Pydantic boundary models.
>
> Implement expense-ai/src/expense_ai/models.py.
>
> Rules:
> - Use Pydantic v2.
> - Every BaseModel uses ConfigDict(extra="forbid", frozen=True).
> - Use populate_by_name=True where aliases are used.
> - Use camelCase aliases matching Java JSON:
>   tenant_id -> tenantId
>   created_at -> createdAt
>   correlation_id -> correlationId
>   merchant_id -> merchantId
>   model_id -> modelId
> - Use Decimal for money, never float.
> - Merchant.amount:
>   Field(ge=Decimal("0"), max_digits=14, decimal_places=2)
> - Include at least one @field_validator:
>   tenant_id must start with "tenant-"
>   correlation_id must start with "corr-"
> - Include at least one @model_validator(mode="after"):
>   high-confidence result confidence >= Decimal("0.90") requires rationale length >= 16.
> - Use confidence as Decimal, not float, to avoid float money/score drift in strict typing.
> - Avoid typing.List, typing.Optional, typing.Union.
> - Use list[X], X | None, tuple[X, ...] if needed.
> - Avoid explicit Any.
>
> Models:
> 1. Merchant
>    id: str
>    tenant_id: str alias tenantId
>    name: str
>    category: str
>    amount: Decimal
>    created_at: datetime alias createdAt
>
> 2. DeductionClassifyRequest
>    correlation_id: str alias correlationId
>    merchant: Merchant
>    model_id: str alias modelId
>    include_rationale: bool default True alias includeRationale
>
> 3. DeductionClassifyResult
>    correlation_id: str alias correlationId
>    merchant_id: str alias merchantId
>    label: str
>    confidence: Decimal Field(ge=Decimal("0"), le=Decimal("1"))
>    deductible: bool
>    rationale: str

### Reply (unedited `src/expense_ai/models.py`)

```python
"""Pydantic v2 boundary models for the Java <-> Python wire contract."""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


class Merchant(BaseModel):  # type: ignore[explicit-any]
    """A merchant record as it crosses the Java/Python boundary."""

    model_config = ConfigDict(
        extra="forbid",
        frozen=True,
        populate_by_name=True,
    )

    id: str
    tenant_id: str = Field(alias="tenantId")
    name: str
    category: str
    amount: Decimal = Field(ge=Decimal("0"), max_digits=14, decimal_places=2)
    created_at: datetime = Field(alias="createdAt")

    @field_validator("tenant_id")
    @classmethod
    def _tenant_id_prefix(cls, value: str) -> str:
        if not value.startswith("tenant-"):
            raise ValueError("tenant_id must start with 'tenant-'")
        return value


class DeductionClassifyRequest(BaseModel):  # type: ignore[explicit-any]
    """Envelope sent from the Python sidecar to the LLM proxy."""

    model_config = ConfigDict(
        extra="forbid",
        frozen=True,
        populate_by_name=True,
    )

    correlation_id: str = Field(alias="correlationId")
    merchant: Merchant
    model_id: str = Field(alias="modelId")
    include_rationale: bool = Field(default=True, alias="includeRationale")

    @field_validator("correlation_id")
    @classmethod
    def _correlation_id_prefix(cls, value: str) -> str:
        if not value.startswith("corr-"):
            raise ValueError("correlation_id must start with 'corr-'")
        return value


class DeductionClassifyResult(BaseModel):  # type: ignore[explicit-any]
    """Result returned from the LLM proxy back to the sidecar caller."""

    model_config = ConfigDict(
        extra="forbid",
        frozen=True,
        populate_by_name=True,
    )

    correlation_id: str = Field(alias="correlationId")
    merchant_id: str = Field(alias="merchantId")
    label: str
    confidence: Decimal = Field(ge=Decimal("0"), le=Decimal("1"))
    deductible: bool
    rationale: str

    @field_validator("correlation_id")
    @classmethod
    def _correlation_id_prefix(cls, value: str) -> str:
        if not value.startswith("corr-"):
            raise ValueError("correlation_id must start with 'corr-'")
        return value

    @model_validator(mode="after")
    def _high_confidence_requires_rationale(self) -> DeductionClassifyResult:
        if self.confidence >= Decimal("0.90") and len(self.rationale) < 16:
            raise ValueError(
                "high-confidence result (>=0.90) requires rationale of at least 16 chars"
            )
        return self
```

---

## Exchange 2 — Client

### Prompt (verbatim, Phase 5 of the W7D1 brief)

> Phase 5 — implement httpx client.
>
> Implement expense-ai/src/expense_ai/client.py.
>
> Requirements:
> - Synchronous LlmProxyClient using httpx.Client.
> - Explicit timeout via httpx.Timeout(settings.proxy_timeout_seconds).
> - Correlation ID propagation:
>   request envelope correlation_id -> HTTP header x-correlation-id.
> - Authorization header:
>   Bearer {settings.proxy_api_key.get_secret_value()}
>   This is the only place get_secret_value() is used.
> - Structured JSON logging using stdlib logging.
>   Each log message should be JSON text, for example json.dumps({...}).
>   Log event names:
>     proxy.call.start
>     proxy.call.http_status
>     proxy.call.ok
>     proxy.call.retryable_error
>   Every log line should carry:
>     event
>     correlation_id
>     tenant_id
>   Never log the API key.
> - Retry with tenacity exponential jitter:
>   stop_after_attempt(settings.proxy_max_retries)
>   wait_exponential_jitter(initial=0.5, max=8.0)
> - Retry only:
>   httpx.TimeoutException
>   httpx.NetworkError
>   httpx.HTTPStatusError where response.status_code >= 500
> - Do NOT retry 4xx.
> - Avoid explicit Any.
> - Do not use bare except.
> - Provide close(), __enter__, __exit__.
>
> Important: implement a retry predicate function like:
> def _is_retryable_exception(exc: BaseException) -> bool:
>     ...
> so 400s are not retried.

### Reply (unedited `src/expense_ai/client.py`)

```python
"""Synchronous httpx-based client for the LLM proxy.

Design contract:

* Explicit ``httpx.Timeout`` — never rely on default (infinite) timeouts.
* Correlation IDs from the request envelope are propagated as
  ``x-correlation-id`` so the proxy and downstream systems can join logs.
* The API key travels only in the ``Authorization`` header. It is stored as
  ``SecretStr`` and only ``get_secret_value()`` is called here — nowhere else.
* Retries use tenacity with exponential jitter and are strictly limited to
  transient failures: timeouts, network errors, and HTTP 5xx.
* 4xx responses fail fast. Retrying a client error would just burn quota.
* Every log line is a JSON object with an ``event`` name plus
  ``correlation_id`` and ``tenant_id``. The API key is never logged.
"""

from __future__ import annotations

import json
import logging
from types import TracebackType

import httpx
from tenacity import (
    RetryError,
    Retrying,
    retry_if_exception,
    stop_after_attempt,
    wait_exponential_jitter,
)

from .models import DeductionClassifyRequest, DeductionClassifyResult
from .settings import ExpenseAiSettings

logger = logging.getLogger("expense_ai.client")


def _is_retryable_exception(exc: BaseException) -> bool:
    """Return True only for transient failures worth retrying."""
    if isinstance(exc, httpx.TimeoutException):
        return True
    if isinstance(exc, httpx.NetworkError):
        return True
    if isinstance(exc, httpx.HTTPStatusError):
        return exc.response.status_code >= 500
    return False


class LlmProxyClient:
    """Synchronous client for the LLM proxy service."""

    def __init__(self, settings: ExpenseAiSettings) -> None:
        self._settings = settings
        self._client = httpx.Client(
            base_url=str(settings.proxy_base_url),
            timeout=httpx.Timeout(settings.proxy_timeout_seconds),
        )

    def __enter__(self) -> LlmProxyClient:
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        self.close()

    def close(self) -> None:
        self._client.close()

    def classify_deduction(self, request: DeductionClassifyRequest) -> DeductionClassifyResult:
        """Call the proxy's deduction classification endpoint."""
        tenant_id = self._settings.tenant_id
        correlation_id = request.correlation_id

        self._log(
            "proxy.call.start",
            correlation_id=correlation_id,
            tenant_id=tenant_id,
            model_id=request.model_id,
        )

        try:
            for attempt in Retrying(
                stop=stop_after_attempt(self._settings.proxy_max_retries),
                wait=wait_exponential_jitter(initial=0.5, max=8.0),
                retry=retry_if_exception(_is_retryable_exception),
                reraise=True,
            ):
                with attempt:
                    response = self._send(request, correlation_id)
                    self._log(
                        "proxy.call.http_status",
                        correlation_id=correlation_id,
                        tenant_id=tenant_id,
                        status_code=response.status_code,
                    )
                    try:
                        response.raise_for_status()
                    except httpx.HTTPStatusError as http_exc:
                        if http_exc.response.status_code >= 500:
                            self._log(
                                "proxy.call.retryable_error",
                                correlation_id=correlation_id,
                                tenant_id=tenant_id,
                                status_code=http_exc.response.status_code,
                            )
                        raise
                    result = DeductionClassifyResult.model_validate_json(response.content)
                    self._log(
                        "proxy.call.ok",
                        correlation_id=correlation_id,
                        tenant_id=tenant_id,
                        label=result.label,
                    )
                    return result
        except RetryError as retry_err:  # pragma: no cover - reraise=True path
            raise retry_err

        # Unreachable — Retrying with reraise=True either returns or raises.
        raise RuntimeError("Retrying loop exited without returning a result")

    def _send(self, request: DeductionClassifyRequest, correlation_id: str) -> httpx.Response:
        headers = {
            "authorization": (f"Bearer {self._settings.proxy_api_key.get_secret_value()}"),
            "content-type": "application/json",
            "x-correlation-id": correlation_id,
        }
        body = request.model_dump_json(by_alias=True)
        return self._client.post(
            "/v1/deductions/classify",
            content=body,
            headers=headers,
        )

    def _log(self, event: str, **fields: object) -> None:
        payload: dict[str, object] = {"event": event}
        payload.update(fields)
        logger.info(json.dumps(payload, sort_keys=True))
```

---

## What changed between the raw reply and what's committed

Only two things, both driven by the local quality gate, not by taste:

1. `ruff format` normalised whitespace in `client.py` (line wrapping around
   two long signatures). No semantic change.
2. `mypy --strict` with `disallow_any_explicit = true` flagged Pydantic 2's
   synthesized `__init__(**data: Any)`. Fix: enable the `pydantic.mypy`
   plugin, and add a targeted `# type: ignore[explicit-any]` on the four
   `BaseModel` / `BaseSettings` class definitions (visible above on lines
   11, 35, 57 of `models.py`). No other `Any` was accepted anywhere in
   `src/` or `tests/`.

## Accept / reject summary

Accepted from the reply on first read:

- The `extra="forbid"` + `populate_by_name=True` + camelCase-alias approach
  for the Java/Python boundary. This is exactly what protects the wire
  contract when a Java field is renamed or added.
- Named retry predicate (`_is_retryable_exception`) rather than an inline
  lambda inside `Retrying(...)`, because it is directly unit-testable.

Rejected / rewritten during initial authoring:

- A first pass suggested `str` for the API key. Replaced with `SecretStr`
  so `repr()` and structured logs never leak it, and the value is unwrapped
  in exactly one line inside `client.py`.
- Old-style `typing.List` / `typing.Optional` / `typing.Union` imports.
  Rejected in favour of PEP 585 / PEP 604 built-ins, and locked in with
  `disallow_any_explicit`.
- Suggestion to retry 4xx "just in case". Rejected — client errors will
  not become non-client on retry; retrying wastes quota. The predicate is
  explicit about this and there is a unit test asserting no-retry on 400.
