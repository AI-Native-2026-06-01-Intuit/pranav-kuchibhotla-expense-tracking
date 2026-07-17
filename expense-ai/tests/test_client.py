"""Tests for LlmProxyClient using respx to mock the wire."""

from __future__ import annotations

import json
import logging
from datetime import UTC, datetime
from decimal import Decimal

import httpx
import pytest
import respx

from expense_ai.client import LlmProxyClient, _is_retryable_exception
from expense_ai.models import DeductionClassifyRequest, Merchant
from expense_ai.settings import ExpenseAiSettings

SECRET_VALUE = "test-key-do-not-log"
BASE_URL = "http://proxy.local"


@pytest.fixture
def settings(monkeypatch: pytest.MonkeyPatch) -> ExpenseAiSettings:
    monkeypatch.setenv("EXPENSE_AI_PROXY_BASE_URL", BASE_URL)
    monkeypatch.setenv("EXPENSE_AI_PROXY_API_KEY", SECRET_VALUE)
    monkeypatch.setenv("EXPENSE_AI_TENANT_ID", "tenant-synth")
    monkeypatch.setenv("EXPENSE_AI_MODEL_ID", "model-x")
    monkeypatch.setenv("EXPENSE_AI_PROXY_MAX_RETRIES", "3")
    monkeypatch.setenv("EXPENSE_AI_PROXY_TIMEOUT_SECONDS", "5")
    return ExpenseAiSettings()


@pytest.fixture
def sample_request() -> DeductionClassifyRequest:
    merchant = Merchant(
        id="merchant-001",
        tenant_id="tenant-synth",
        name="Acme Office Supplies",
        category="office_supplies",
        amount=Decimal("123.45"),
        created_at=datetime(2026, 1, 15, 12, 0, tzinfo=UTC),
    )
    return DeductionClassifyRequest(
        correlation_id="corr-abc-123",
        merchant=merchant,
        model_id="model-x",
    )


def _success_body(correlation_id: str, merchant_id: str) -> bytes:
    return json.dumps(
        {
            "correlationId": correlation_id,
            "merchantId": merchant_id,
            "label": "office_supplies",
            "confidence": "0.42",
            "deductible": True,
            "rationale": "office supplies typically qualify",
        }
    ).encode("utf-8")


def test_is_retryable_exception_matrix() -> None:
    req = httpx.Request("POST", f"{BASE_URL}/x")
    assert _is_retryable_exception(httpx.ConnectError("boom", request=req)) is True
    assert _is_retryable_exception(httpx.ReadTimeout("slow", request=req)) is True

    resp_500 = httpx.Response(500, request=req)
    resp_400 = httpx.Response(400, request=req)
    assert (
        _is_retryable_exception(httpx.HTTPStatusError("500", request=req, response=resp_500))
        is True
    )
    assert (
        _is_retryable_exception(httpx.HTTPStatusError("400", request=req, response=resp_400))
        is False
    )
    assert _is_retryable_exception(ValueError("nope")) is False


@respx.mock
def test_happy_path_returns_result(
    settings: ExpenseAiSettings,
    sample_request: DeductionClassifyRequest,
    caplog: pytest.LogCaptureFixture,
) -> None:
    route = respx.post(f"{BASE_URL}/v1/deductions/classify").mock(
        return_value=httpx.Response(
            200,
            content=_success_body(sample_request.correlation_id, sample_request.merchant.id),
        )
    )

    caplog.set_level(logging.INFO, logger="expense_ai.client")
    with LlmProxyClient(settings) as client:
        result = client.classify_deduction(sample_request)

    assert route.called
    assert route.call_count == 1
    assert result.merchant_id == sample_request.merchant.id
    assert result.confidence == Decimal("0.42")

    sent = route.calls[0].request
    assert sent.headers["x-correlation-id"] == sample_request.correlation_id
    assert sent.headers["authorization"] == f"Bearer {SECRET_VALUE}"

    # correlation id shows up in logs, API key never does
    assert sample_request.correlation_id in caplog.text
    assert SECRET_VALUE not in caplog.text


@respx.mock
def test_retry_on_503_exhausts_attempts(
    settings: ExpenseAiSettings,
    sample_request: DeductionClassifyRequest,
) -> None:
    route = respx.post(f"{BASE_URL}/v1/deductions/classify").mock(
        return_value=httpx.Response(503, text="unavailable")
    )
    with (
        LlmProxyClient(settings) as client,
        pytest.raises(httpx.HTTPStatusError),
    ):
        client.classify_deduction(sample_request)
    assert route.call_count == 3


@respx.mock
def test_no_retry_on_400(
    settings: ExpenseAiSettings,
    sample_request: DeductionClassifyRequest,
) -> None:
    route = respx.post(f"{BASE_URL}/v1/deductions/classify").mock(
        return_value=httpx.Response(400, text="bad request")
    )
    with (
        LlmProxyClient(settings) as client,
        pytest.raises(httpx.HTTPStatusError),
    ):
        client.classify_deduction(sample_request)
    assert route.call_count == 1


@respx.mock
def test_retry_on_timeout(
    settings: ExpenseAiSettings,
    sample_request: DeductionClassifyRequest,
) -> None:
    route = respx.post(f"{BASE_URL}/v1/deductions/classify").mock(
        side_effect=httpx.ReadTimeout("slow")
    )
    with (
        LlmProxyClient(settings) as client,
        pytest.raises(httpx.ReadTimeout),
    ):
        client.classify_deduction(sample_request)
    assert route.call_count == 3


@respx.mock
def test_retry_then_success(
    settings: ExpenseAiSettings,
    sample_request: DeductionClassifyRequest,
) -> None:
    ok = httpx.Response(
        200,
        content=_success_body(sample_request.correlation_id, sample_request.merchant.id),
    )
    route = respx.post(f"{BASE_URL}/v1/deductions/classify").mock(
        side_effect=[httpx.Response(502, text="bad gw"), ok]
    )
    with LlmProxyClient(settings) as client:
        result = client.classify_deduction(sample_request)
    assert route.call_count == 2
    assert result.label == "office_supplies"


@respx.mock
def test_log_events_have_correlation_id(
    settings: ExpenseAiSettings,
    sample_request: DeductionClassifyRequest,
    caplog: pytest.LogCaptureFixture,
) -> None:
    respx.post(f"{BASE_URL}/v1/deductions/classify").mock(
        return_value=httpx.Response(
            200,
            content=_success_body(sample_request.correlation_id, sample_request.merchant.id),
        )
    )
    caplog.set_level(logging.INFO, logger="expense_ai.client")
    with LlmProxyClient(settings) as client:
        client.classify_deduction(sample_request)

    events: list[str] = []
    for rec in caplog.records:
        parsed = json.loads(rec.getMessage())
        assert parsed["correlation_id"] == sample_request.correlation_id
        assert parsed["tenant_id"] == settings.tenant_id
        events.append(str(parsed["event"]))

    assert "proxy.call.start" in events
    assert "proxy.call.http_status" in events
    assert "proxy.call.ok" in events
