"""Redis semantic cache tests: tenant scoping, epoch bumping, near-dup hit."""

from __future__ import annotations

from collections.abc import Iterator

import numpy as np
import pytest
import redis
from numpy.typing import NDArray
from testcontainers.redis import RedisContainer

from expense_ai.cache import (
    bump_epoch,
    cache_lookup,
    cache_store,
    get_epoch,
)

pytestmark = [pytest.mark.docker, pytest.mark.redis]


@pytest.fixture(scope="module")
def redis_client() -> Iterator[redis.Redis]:
    with RedisContainer("redis:7-alpine") as rc:
        host = rc.get_container_host_ip()
        port = int(rc.get_exposed_port(6379))
        client = redis.Redis(host=host, port=port, db=0)
        # sanity
        assert client.ping() is True
        yield client
        client.close()


@pytest.fixture(autouse=True)
def _flush(redis_client: redis.Redis) -> Iterator[None]:
    redis_client.flushdb()
    yield


def _vec(seed: int) -> NDArray[np.float32]:
    rng = np.random.default_rng(seed)
    v = rng.standard_normal(384).astype(np.float32)
    n = float(np.linalg.norm(v)) or 1.0
    return (v / n).astype(np.float32)


def _answer(tenant: str) -> dict[str, object]:
    return {
        "answer": f"scoped to {tenant}",
        "citations": [{"chunk_id": "c1", "tenant_id": tenant}],
    }


def test_near_duplicate_vectors_hit_same_key(redis_client: redis.Redis) -> None:
    # Build vectors that fall in the same rounded bucket by construction:
    # start from an integer-scaled vector and add tiny sub-bucket noise.
    base_int = np.array([1, 2, -3, 0, 5] * 76 + [1, 2, -3, 0], dtype=np.int32)
    q = base_int.astype(np.float32) / 100.0
    q_near = q + np.full_like(q, 0.0001, dtype=np.float32)

    cache_store(redis_client, q, "tenant-a", _answer("tenant-a"))
    hit = cache_lookup(redis_client, q_near, "tenant-a")
    assert hit is not None
    assert hit["answer"] == "scoped to tenant-a"


def test_same_vector_different_tenant_is_miss(redis_client: redis.Redis) -> None:
    q = _vec(1)
    cache_store(redis_client, q, "tenant-a", _answer("tenant-a"))
    hit = cache_lookup(redis_client, q, "tenant-b")
    assert hit is None


def test_bump_epoch_invalidates(redis_client: redis.Redis) -> None:
    q = _vec(1)
    cache_store(redis_client, q, "tenant-a", _answer("tenant-a"))
    assert cache_lookup(redis_client, q, "tenant-a") is not None
    prior = get_epoch(redis_client, "tenant-a")
    new_epoch = bump_epoch(redis_client, "tenant-a")
    assert new_epoch == prior + 1
    assert cache_lookup(redis_client, q, "tenant-a") is None


def test_cached_citation_tenant_mismatch_is_miss(redis_client: redis.Redis) -> None:
    q = _vec(1)
    # Deliberately mis-scoped: writing tenant-a key with a citation
    # pointing at tenant-b. Defense-in-depth check should reject on read.
    bad = {
        "answer": "leaky",
        "citations": [{"chunk_id": "c1", "tenant_id": "tenant-b"}],
    }
    cache_store(redis_client, q, "tenant-a", bad)
    hit = cache_lookup(redis_client, q, "tenant-a")
    assert hit is None


def test_get_epoch_defaults_to_zero(redis_client: redis.Redis) -> None:
    assert get_epoch(redis_client, "brand-new") == 0
