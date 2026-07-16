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
