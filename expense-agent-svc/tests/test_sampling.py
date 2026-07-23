"""ProductionSampler contract tests.

Cover:

* Sample-rate boundaries (0 never, 1 always, deterministic fractional).
* ``submit`` never blocks the caller and does not delay a hypothetical
  user-visible response — verified by asserting the caller returns
  before the evaluator finishes.
* Failed evaluator invocations are swallowed and never write metadata.
* An evaluator that returns non-numeric values writes nothing (no
  fabricated metrics).
* Missing evaluator credentials mean the sampler is disabled and
  ``should_sample`` always returns False.
* Empty-context samples (refusal path) are never sent to the evaluator.
* ``aclose`` awaits every in-flight background task so shutdown drains
  cleanly.
* Bounded contexts / question / answer sizes.
* Three required metric names.
"""

from __future__ import annotations

import asyncio
from collections.abc import Mapping
from typing import Any

import pytest

from expense_agent_svc.sampling import (
    MAX_CONTEXT_CHARS,
    MAX_CONTEXTS,
    REQUIRED_METRICS,
    GroundedSample,
    ProductionSampler,
    bounded_contexts,
    build_sample,
    build_sampler,
)

# ---------- Bounded sample helpers ----------


def test_bounded_contexts_caps_count_and_length() -> None:
    docs: list[dict[str, object]] = [{"quote": "q" * 500} for _ in range(20)]
    tool_results: dict[str, object] = {f"tool.{i}": "x" * 500 for i in range(20)}
    contexts = bounded_contexts(docs=docs, tool_results=tool_results)
    assert len(contexts) == MAX_CONTEXTS
    for context in contexts:
        assert len(context) <= MAX_CONTEXT_CHARS


def test_bounded_contexts_ignores_docs_without_quote() -> None:
    docs: list[dict[str, object]] = [{"chunk_id": "c1"}, {"quote": "one two three four five"}]
    contexts = bounded_contexts(docs=docs, tool_results={})
    assert contexts == ("one two three four five",)


def test_build_sample_trims_question_and_answer() -> None:
    sample = build_sample(
        trace_id="run-1",
        question="q" * 5_000,
        answer="a" * 5_000,
        docs=[{"quote": "abcdefghijk"}],
        tool_results={},
        tenant_id="tenant-a",
    )
    assert len(sample.question) <= 2_000
    assert len(sample.answer) <= 2_000
    assert sample.tenant_id == "tenant-a"
    assert sample.contexts == ("abcdefghijk",)


def test_required_metrics_are_the_three_from_the_rubric() -> None:
    assert set(REQUIRED_METRICS) == {
        "faithfulness",
        "context_recall",
        "answer_relevancy",
    }


# ---------- Evaluator + writer fakes ----------


class _FakeEvaluator:
    """Deterministic evaluator that records every call."""

    def __init__(
        self,
        *,
        metrics: Mapping[str, float] | None = None,
        raise_on_call: bool = False,
        delay: float = 0.0,
    ) -> None:
        self._metrics = metrics
        self._raise = raise_on_call
        self._delay = delay
        self.calls: list[GroundedSample] = []

    async def evaluate(self, sample: GroundedSample) -> Mapping[str, float]:
        self.calls.append(sample)
        if self._delay:
            await asyncio.sleep(self._delay)
        if self._raise:
            raise RuntimeError("simulated evaluator failure")
        return dict(self._metrics or {})


class _RecordingWriter:
    def __init__(self) -> None:
        self.calls: list[tuple[str | None, dict[str, object]]] = []

    async def __call__(
        self,
        trace_id: str | None,
        metadata: Mapping[str, float | bool | str],
    ) -> None:
        self.calls.append((trace_id, dict(metadata)))


def _sample(
    *,
    tenant: str = "tenant-a",
    with_context: bool = True,
    trace: str | None = "run-1",
) -> GroundedSample:
    contexts = ("context body ten+ chars",) if with_context else ()
    return GroundedSample(
        trace_id=trace,
        question="policy?",
        answer="policy answer",
        contexts=contexts,
        reference=None,
        tenant_id=tenant,
    )


# ---------- Sampling decision ----------


def test_rate_zero_never_samples() -> None:
    evaluator = _FakeEvaluator(metrics=dict.fromkeys(REQUIRED_METRICS, 0.9))
    s = ProductionSampler(sample_rate=0.0, evaluator=evaluator)
    for _ in range(50):
        assert s.should_sample() is False


def test_rate_one_always_samples() -> None:
    evaluator = _FakeEvaluator(metrics=dict.fromkeys(REQUIRED_METRICS, 0.9))
    s = ProductionSampler(sample_rate=1.0, evaluator=evaluator)
    for _ in range(50):
        assert s.should_sample() is True


def test_deterministic_fractional_rate() -> None:
    """Injected random source drives the decision, so the test is
    deterministic regardless of the process-wide random state."""
    evaluator = _FakeEvaluator(metrics=dict.fromkeys(REQUIRED_METRICS, 0.9))
    values = iter([0.02, 0.5, 0.999, 0.001])
    s = ProductionSampler(
        sample_rate=0.05,
        evaluator=evaluator,
        random_source=lambda: next(values),
    )
    # 0.02 < 0.05 -> True
    assert s.should_sample() is True
    # 0.5 >= 0.05 -> False
    assert s.should_sample() is False
    # 0.999 >= 0.05 -> False
    assert s.should_sample() is False
    # 0.001 < 0.05 -> True
    assert s.should_sample() is True


def test_disabled_sampler_when_no_evaluator() -> None:
    s = build_sampler(sample_rate=0.5, evaluator=None)
    assert s.enabled is False
    assert s.should_sample() is False


def test_invalid_rate_rejected() -> None:
    evaluator = _FakeEvaluator()
    with pytest.raises(ValueError):
        ProductionSampler(sample_rate=-0.1, evaluator=evaluator)
    with pytest.raises(ValueError):
        ProductionSampler(sample_rate=1.1, evaluator=evaluator)


# ---------- submit behaviour ----------


@pytest.mark.asyncio
async def test_submit_writes_the_three_required_metrics() -> None:
    evaluator = _FakeEvaluator(
        metrics={"faithfulness": 0.9, "context_recall": 0.85, "answer_relevancy": 0.8},
    )
    writer = _RecordingWriter()
    s = ProductionSampler(
        sample_rate=1.0,
        evaluator=evaluator,
        metadata_writer=writer,
    )
    await s.submit(_sample())
    await s.aclose()

    assert len(evaluator.calls) == 1
    assert len(writer.calls) == 1
    trace_id, metadata = writer.calls[0]
    assert trace_id == "run-1"
    assert metadata["ragas_sampled"] is True
    assert metadata["ragas_faithfulness"] == 0.9
    assert metadata["ragas_context_recall"] == 0.85
    assert metadata["ragas_answer_relevancy"] == 0.8


@pytest.mark.asyncio
async def test_submit_returns_before_evaluator_finishes() -> None:
    """Non-blocking proof: submit returns while the evaluator is still
    running (delay=0.05s). aclose() then awaits completion."""
    evaluator = _FakeEvaluator(
        metrics=dict.fromkeys(REQUIRED_METRICS, 0.9),
        delay=0.05,
    )
    writer = _RecordingWriter()
    s = ProductionSampler(sample_rate=1.0, evaluator=evaluator, metadata_writer=writer)

    started = asyncio.get_event_loop().time()
    await s.submit(_sample())
    submit_elapsed = asyncio.get_event_loop().time() - started
    # Submit itself must return promptly.
    assert submit_elapsed < 0.03
    # Evaluator has not written yet (delay is still burning).
    assert writer.calls == []
    await s.aclose()
    # Now the background task has finished.
    assert len(writer.calls) == 1


@pytest.mark.asyncio
async def test_evaluator_failure_is_swallowed() -> None:
    evaluator = _FakeEvaluator(raise_on_call=True)
    writer = _RecordingWriter()
    s = ProductionSampler(sample_rate=1.0, evaluator=evaluator, metadata_writer=writer)
    await s.submit(_sample())
    await s.aclose()
    assert writer.calls == [], "no metadata must be written when evaluation fails"


@pytest.mark.asyncio
async def test_non_numeric_metric_produces_no_write() -> None:
    """Never fabricate a metric — if the evaluator returned nothing
    usable, we simply do not write a run annotation."""
    evaluator = _FakeEvaluator(
        metrics={
            "faithfulness": "not a number",  # type: ignore[dict-item]
            "context_recall": True,  # bool is rejected by our filter
            "answer_relevancy": None,  # type: ignore[dict-item]
        }
    )
    writer = _RecordingWriter()
    s = ProductionSampler(sample_rate=1.0, evaluator=evaluator, metadata_writer=writer)
    await s.submit(_sample())
    await s.aclose()
    assert writer.calls == []


@pytest.mark.asyncio
async def test_partial_metric_write() -> None:
    """One valid metric is still worth writing."""
    evaluator = _FakeEvaluator(
        metrics={"faithfulness": 0.7},
    )
    writer = _RecordingWriter()
    s = ProductionSampler(sample_rate=1.0, evaluator=evaluator, metadata_writer=writer)
    await s.submit(_sample())
    await s.aclose()
    assert len(writer.calls) == 1
    _tid, meta = writer.calls[0]
    assert meta["ragas_faithfulness"] == 0.7


@pytest.mark.asyncio
async def test_empty_context_sample_is_never_evaluated() -> None:
    """The refusal path produces no grounded context — do not evaluate."""
    evaluator = _FakeEvaluator(metrics=dict.fromkeys(REQUIRED_METRICS, 0.9))
    writer = _RecordingWriter()
    s = ProductionSampler(sample_rate=1.0, evaluator=evaluator, metadata_writer=writer)
    await s.submit(_sample(with_context=False))
    await s.aclose()
    assert evaluator.calls == []
    assert writer.calls == []


@pytest.mark.asyncio
async def test_no_task_survives_aclose() -> None:
    """After aclose(), no in-flight background task remains."""
    evaluator = _FakeEvaluator(
        metrics=dict.fromkeys(REQUIRED_METRICS, 0.9),
        delay=0.02,
    )
    s = ProductionSampler(sample_rate=1.0, evaluator=evaluator)
    for _ in range(4):
        await s.submit(_sample())
    # There are pending tasks now.
    inflight = list(s._tasks)
    assert len(inflight) == 4
    await s.aclose()
    # All tasks are done — no orphans.
    for task in inflight:
        assert task.done()


@pytest.mark.asyncio
async def test_closed_sampler_refuses_new_submissions() -> None:
    evaluator = _FakeEvaluator(metrics=dict.fromkeys(REQUIRED_METRICS, 0.9))
    writer = _RecordingWriter()
    s = ProductionSampler(sample_rate=1.0, evaluator=evaluator, metadata_writer=writer)
    await s.aclose()
    assert s.should_sample() is False
    await s.submit(_sample())
    assert evaluator.calls == []
    assert writer.calls == []


@pytest.mark.asyncio
async def test_disabled_sampler_submit_is_a_noop() -> None:
    s = build_sampler(sample_rate=0.5, evaluator=None)
    await s.submit(_sample())
    await s.aclose()
    # No exception, no state — just prove the call chain worked.
    assert s.enabled is False


def test_build_sampler_returns_production_sampler_when_evaluator_available() -> None:
    class _E:
        async def evaluate(self, sample: GroundedSample) -> Mapping[str, float]:
            del sample
            return dict.fromkeys(REQUIRED_METRICS, 0.9)

    s = build_sampler(sample_rate=0.5, evaluator=_E())
    assert isinstance(s, ProductionSampler)
    assert s.enabled is True


# ---------- No fabricated values in state ----------


def test_grounded_sample_is_immutable() -> None:
    import dataclasses as _dc

    s = _sample()
    with pytest.raises(_dc.FrozenInstanceError):
        s.question = "changed"  # type: ignore[misc]
    _ = Any  # keep import


def test_source_names_metrics_exactly() -> None:
    """The metadata field names must be the stable ones the rubric names."""
    # This is a static check — if these constants ever drift the
    # trajectory eval baseline comparison would silently break.
    assert REQUIRED_METRICS == ("faithfulness", "context_recall", "answer_relevancy")
