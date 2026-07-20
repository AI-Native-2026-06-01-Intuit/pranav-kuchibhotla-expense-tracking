"""Redis semantic cache keyed by tenant_id + epoch + rounded query vector.

Key shape::

    expense_ai:sem:{tenant_id}:e{epoch}:{hash}

* ``tenant_id``: mandatory. Cache entries never cross tenants.
* ``epoch``: bumped whenever a tenant's corpus changes. ``bump_epoch`` is
  the invalidation primitive.
* ``hash``: sha256 of the query vector rounded to 2-decimal fidelity. Two
  near-identical queries share a key without collapsing genuinely different
  intents.

Defense-in-depth: on ``cache_lookup``, we re-check every cached citation's
``tenant_id`` against the requesting tenant. A mismatch is treated as a miss
so a mis-scoped write cannot leak into another tenant's read path.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping, Sequence
from typing import cast

import numpy as np
import redis
from langsmith import traceable
from numpy.typing import NDArray

_KEY_PREFIX = "expense_ai:sem"
_EPOCH_PREFIX = "expense_ai:sem_epoch"


def _epoch_key(tenant_id: str) -> str:
    return f"{_EPOCH_PREFIX}:{tenant_id}"


def get_epoch(r: redis.Redis, tenant_id: str) -> int:
    raw = r.get(_epoch_key(tenant_id))
    if raw is None:
        return 0
    return int(cast(bytes, raw))


def bump_epoch(r: redis.Redis, tenant_id: str) -> int:
    new_val = r.incr(_epoch_key(tenant_id))
    return int(new_val)


def _vector_hash(query_vec: NDArray[np.float32]) -> str:
    rounded = np.round(query_vec * 100).astype(np.int32)
    digest = hashlib.sha256(rounded.tobytes()).hexdigest()
    return digest[:16]


def _cache_key(tenant_id: str, epoch: int, vec_hash: str) -> str:
    return f"{_KEY_PREFIX}:{tenant_id}:e{epoch}:{vec_hash}"


def _citations_all_match_tenant(
    citations: Sequence[Mapping[str, object]],
    tenant_id: str,
) -> bool:
    for c in citations:
        cited = c.get("tenant_id")
        if cited is None or str(cited) != tenant_id:
            return False
    return True


@traceable(run_type="chain", name="expense_ai.cache_lookup")
def cache_lookup(
    r: redis.Redis,
    query_vec: NDArray[np.float32],
    tenant_id: str,
) -> dict[str, object] | None:
    """Return the cached answer or None. Cross-tenant citations force a miss."""
    epoch = get_epoch(r, tenant_id)
    key = _cache_key(tenant_id, epoch, _vector_hash(query_vec))
    raw = r.get(key)
    if raw is None:
        return None
    payload = json.loads(cast(bytes, raw).decode("utf-8"))
    if not isinstance(payload, dict):
        return None
    typed_payload: dict[str, object] = payload
    citations_raw = typed_payload.get("citations")
    if isinstance(citations_raw, list):
        citations: list[Mapping[str, object]] = [c for c in citations_raw if isinstance(c, dict)]
        if not _citations_all_match_tenant(citations, tenant_id):
            return None
    return typed_payload


def cache_store(
    r: redis.Redis,
    query_vec: NDArray[np.float32],
    tenant_id: str,
    answer: Mapping[str, object],
    ttl_seconds: int = 3600,
) -> None:
    """Store ``answer`` under a tenant+epoch scoped key with TTL."""
    epoch = get_epoch(r, tenant_id)
    key = _cache_key(tenant_id, epoch, _vector_hash(query_vec))
    r.set(key, json.dumps(dict(answer)), ex=ttl_seconds)
