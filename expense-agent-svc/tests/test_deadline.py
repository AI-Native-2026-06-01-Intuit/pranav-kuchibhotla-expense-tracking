"""Deadline decorator behaviour.

Cover:

* Slow node -> sentinel copy (with ``deadline_exceeded=True`` and
  ``deadline_limit_s`` appended) within a bounded wall-clock time.
* Fast node returns its own result unchanged.
* Sentinel is copied — successive timeouts do not alias one mutable dict.
* Non-timeout exceptions propagate.
* Function metadata (name / docstring) preserved.
* Metadata callback receives the safe tags.
* Bad ``seconds`` argument is rejected at decorator construction time.
"""

from __future__ import annotations

import asyncio
import time
from collections.abc import Mapping
from typing import Any

import pytest

from expense_agent_svc.nodes._deadline import deadline


@pytest.mark.asyncio
async def test_slow_node_returns_sentinel_within_bounded_time() -> None:
    tags: list[dict[str, object]] = []

    @deadline(
        seconds=0.05,
        sentinel={"answer": "[deadline]", "visited_nodes": ["retrieval_agent"]},
        tag_current_run=tags.append,
    )
    async def slow() -> Mapping[str, object]:
        await asyncio.sleep(1.0)
        return {"answer": "not reached"}

    started = time.perf_counter()
    result = await slow()
    elapsed = time.perf_counter() - started

    assert elapsed < 0.5, f"deadline did not enforce, took {elapsed:.2f}s"
    assert result["answer"] == "[deadline]"
    assert result["deadline_exceeded"] is True
    assert result["deadline_limit_s"] == 0.05
    assert tags and tags[0]["deadline_exceeded"] is True
    assert tags[0]["node"] == "slow"


@pytest.mark.asyncio
async def test_sentinel_copies_are_independent() -> None:
    # The important invariant is that the *outer* dict is fresh each
    # time — the reducer sees a distinct partial-state mapping and
    # cannot accidentally mutate a shared object across timeouts. Deep
    # copies of inner values would double the sentinel size for
    # negligible additional safety.
    @deadline(
        seconds=0.05,
        sentinel={"docs": [], "visited_nodes": ["retrieval_agent"]},
        tag_current_run=lambda _md: None,
    )
    async def slow() -> Mapping[str, object]:
        await asyncio.sleep(1.0)
        return {}

    r1 = await slow()
    r2 = await slow()
    assert r1 is not r2
    # Mutating one copy must not affect the other.
    r1_dict = dict(r1)
    r1_dict["deadline_exceeded"] = "mutated"
    assert r2["deadline_exceeded"] is True


@pytest.mark.asyncio
async def test_fast_node_returns_normally() -> None:
    @deadline(
        seconds=1.0,
        sentinel={"answer": "[deadline]"},
        tag_current_run=lambda _md: None,
    )
    async def fast() -> Mapping[str, object]:
        return {"answer": "done", "cost_usd_e5": 42}

    result = await fast()
    assert result == {"answer": "done", "cost_usd_e5": 42}


@pytest.mark.asyncio
async def test_non_timeout_exception_propagates() -> None:
    @deadline(
        seconds=1.0,
        sentinel={"answer": "[deadline]"},
        tag_current_run=lambda _md: None,
    )
    async def boom() -> Mapping[str, object]:
        raise RuntimeError("real failure")

    with pytest.raises(RuntimeError, match="real failure"):
        await boom()


def test_preserves_function_metadata() -> None:
    @deadline(
        seconds=1.0,
        sentinel={},
        tag_current_run=lambda _md: None,
    )
    async def my_named_node() -> Mapping[str, object]:
        """My node docstring."""
        return {}

    assert my_named_node.__name__ == "my_named_node"
    assert my_named_node.__doc__ == "My node docstring."


def test_rejects_non_positive_seconds() -> None:
    with pytest.raises(ValueError):
        deadline(seconds=0, sentinel={})
    with pytest.raises(ValueError):
        deadline(seconds=-0.5, sentinel={})


def test_rejects_bad_seconds_type() -> None:
    with pytest.raises(TypeError):
        deadline(seconds="5", sentinel={})  # type: ignore[arg-type]
    with pytest.raises(TypeError):
        deadline(seconds=True, sentinel={})


@pytest.mark.asyncio
async def test_default_tagger_is_safe_without_langsmith() -> None:
    # Without an injected tagger, the default one must not raise even
    # when no LangSmith run tree is active.
    @deadline(seconds=0.05, sentinel={"answer": "[deadline]"})
    async def slow() -> Mapping[str, object]:
        await asyncio.sleep(1.0)
        return {}

    # Should not raise even without a tag_current_run injection.
    result: Any = await slow()
    assert result["deadline_exceeded"] is True
