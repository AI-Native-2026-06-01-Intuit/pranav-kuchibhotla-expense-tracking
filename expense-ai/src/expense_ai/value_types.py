"""Frozen internal value types used by the sidecar.

These are not part of the wire contract — they are strictly-typed, hashable
records used internally (e.g. as cache keys or correlation context).
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime


@dataclass(frozen=True, slots=True)
class ProxyCallKey:
    """Deduplication key for a single proxy call."""

    correlation_id: str
    model_id: str
    prompt_hash: str


@dataclass(frozen=True, slots=True)
class CorrelationContext:
    """Correlation context propagated across a single logical request."""

    correlation_id: str
    tenant_id: str
    started_at: datetime
    tags: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class RetryPlan:
    """Immutable retry policy description."""

    max_attempts: int
    retryable_statuses: frozenset[int]
