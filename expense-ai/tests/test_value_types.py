"""Tests for internal frozen value types."""

from __future__ import annotations

from dataclasses import FrozenInstanceError
from datetime import UTC, datetime

import pytest

from expense_ai.value_types import CorrelationContext, ProxyCallKey, RetryPlan


def test_proxy_call_key_is_hashable_and_frozen() -> None:
    key = ProxyCallKey("corr-1", "model-x", "abc123")
    assert hash(key) == hash(ProxyCallKey("corr-1", "model-x", "abc123"))
    with pytest.raises(FrozenInstanceError):
        key.correlation_id = "corr-2"  # type: ignore[misc]


def test_correlation_context_uses_immutable_collection() -> None:
    ctx = CorrelationContext(
        correlation_id="corr-1",
        tenant_id="tenant-synth",
        started_at=datetime(2026, 2, 1, tzinfo=UTC),
        tags=("beta", "shadow"),
    )
    assert isinstance(ctx.tags, tuple)
    assert hash(ctx) == hash(ctx)


def test_retry_plan_uses_frozenset() -> None:
    plan = RetryPlan(max_attempts=3, retryable_statuses=frozenset({502, 503, 504}))
    assert 503 in plan.retryable_statuses
    with pytest.raises(FrozenInstanceError):
        plan.max_attempts = 5  # type: ignore[misc]
