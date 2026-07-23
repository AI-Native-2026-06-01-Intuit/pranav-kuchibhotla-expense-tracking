"""Production RAGAS sampler.

Samples a small fraction of completed *grounded* answers and evaluates
them asynchronously through an injected :class:`RagasEvaluator`. The
sampler MUST NOT delay the user-visible channel-2 :class:`FinalAnswer`
frame — evaluation runs on background tasks that the sampler itself
owns, so shutdown drains them cleanly (no orphan asyncio tasks left
behind).

Design guardrails:

* No embeddings or raw metadata are captured — the sampler only sees
  bounded doc quotes and bounded tool-result text.
* When the evaluator is not configured (missing credentials), the
  sampler is disabled and every ``should_sample`` call returns
  ``False``. The user request path is unaffected.
* Evaluator failures are logged at a coarse category and swallowed.
* Metric values are never fabricated — a failed evaluation writes
  nothing.
"""

from __future__ import annotations

import asyncio
import logging
import random
from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass, field
from typing import Protocol

_log = logging.getLogger("expense_agent_svc.sampling")

# Bounded text sizes so a huge context cannot balloon a background
# evaluator task's memory footprint. These match the synthesis prompt
# bounds so what the evaluator sees is what synthesis grounded on.
MAX_CONTEXTS = 8
MAX_CONTEXT_CHARS = 240
MAX_QUESTION_CHARS = 2_000
MAX_ANSWER_CHARS = 2_000


# --- Bounded sample ---------------------------------------------------------


@dataclass(frozen=True)
class GroundedSample:
    """Bounded per-request evidence that a background evaluator receives.

    ``contexts`` is a tuple (immutable) of bounded quote strings — one
    per doc / tool result. ``reference`` is optional: production
    samples do not carry ground-truth references, but the trajectory
    eval CLI (Phase 18) can construct GroundedSample instances that
    do. ``trace_id`` is the LangSmith run id, if the request had one,
    so metrics land on the right run.
    """

    trace_id: str | None
    question: str
    answer: str
    contexts: tuple[str, ...]
    reference: str | None
    tenant_id: str


def bounded_contexts(
    *,
    docs: Mapping[str, object] | list[dict[str, object]] | None,
    tool_results: Mapping[str, object] | None,
) -> tuple[str, ...]:
    """Return up to :data:`MAX_CONTEXTS` bounded context strings.

    Called at the stream-completion boundary in the SSE bridge. Only
    reads ``quote`` fields on docs and stringified tool-result values —
    embeddings, doc metadata, and full prompts never leak in.
    """
    out: list[str] = []
    if isinstance(docs, list):
        for entry in docs[:MAX_CONTEXTS]:
            if isinstance(entry, Mapping):
                quote = entry.get("quote")
                if isinstance(quote, str) and quote:
                    out.append(quote[:MAX_CONTEXT_CHARS])
    if isinstance(tool_results, Mapping):
        for value in tool_results.values():
            if len(out) >= MAX_CONTEXTS:
                break
            out.append(str(value)[:MAX_CONTEXT_CHARS])
    return tuple(out[:MAX_CONTEXTS])


def build_sample(
    *,
    trace_id: str | None,
    question: str,
    answer: str,
    docs: Mapping[str, object] | list[dict[str, object]] | None,
    tool_results: Mapping[str, object] | None,
    tenant_id: str,
    reference: str | None = None,
) -> GroundedSample:
    return GroundedSample(
        trace_id=trace_id,
        question=question[:MAX_QUESTION_CHARS],
        answer=answer[:MAX_ANSWER_CHARS],
        contexts=bounded_contexts(docs=docs, tool_results=tool_results),
        reference=reference,
        tenant_id=tenant_id,
    )


# --- Evaluator + metadata writer contracts ---------------------------------


REQUIRED_METRICS = ("faithfulness", "context_recall", "answer_relevancy")


class RagasEvaluator(Protocol):
    """Structural type for an async RAGAS-shaped evaluator.

    Tests inject a deterministic fake. The default production
    evaluator (:func:`default_ragas_evaluator`) offloads a synchronous
    ragas invocation through :func:`asyncio.to_thread`.
    """

    async def evaluate(self, sample: GroundedSample) -> Mapping[str, float]: ...


MetadataWriter = Callable[[str | None, Mapping[str, float | bool | str]], Awaitable[None]]


async def _default_metadata_writer(
    trace_id: str | None,
    metadata: Mapping[str, float | bool | str],
) -> None:
    """Attach ``metadata`` to a LangSmith run when one exists.

    Falls silent on any langsmith failure — this is telemetry, not
    correctness.
    """
    if trace_id is None:
        return
    try:
        from langsmith import Client
    except ImportError:
        return
    try:
        client = Client()
        await asyncio.to_thread(
            client.update_run,
            trace_id,
            extra={"metadata": dict(metadata)},
        )
    except Exception:
        _log.warning("sampling.metadata_write_failed")


# --- Sampler ----------------------------------------------------------------


class ProductionSampler:
    """Owns the sampling decision + the background evaluator tasks.

    Not thread-safe — one sampler per process, driven by the FastAPI
    lifespan. Callers use :meth:`should_sample` to skip cheap paths
    early, then :meth:`submit` with a :class:`GroundedSample` that has
    already been trimmed to bounded sizes.

    ``aclose()`` awaits any in-flight background evaluations so a pod
    shutdown does not leave a dangling task.
    """

    def __init__(
        self,
        *,
        sample_rate: float,
        evaluator: RagasEvaluator | None,
        random_source: Callable[[], float] | None = None,
        metadata_writer: MetadataWriter | None = None,
    ) -> None:
        if not 0.0 <= sample_rate <= 1.0:
            raise ValueError("sample_rate must be within [0.0, 1.0]")
        self._sample_rate = sample_rate
        self._evaluator = evaluator
        self._random = random_source if random_source is not None else random.random
        self._metadata_writer = (
            metadata_writer if metadata_writer is not None else _default_metadata_writer
        )
        # Track every scheduled task so aclose() can await them.
        self._tasks: set[asyncio.Task[None]] = set()
        self._closed = False

    @property
    def enabled(self) -> bool:
        """True iff an evaluator is configured and rate > 0."""
        return self._evaluator is not None and self._sample_rate > 0.0

    def should_sample(self) -> bool:
        """Return whether the next completed answer should be evaluated.

        Uses the injected ``random_source`` so tests can force True/False
        deterministically. Disabled sampler always returns False.
        """
        if not self.enabled or self._closed:
            return False
        return self._random() < self._sample_rate

    async def submit(self, sample: GroundedSample) -> None:
        """Schedule background evaluation for ``sample`` — returns immediately.

        The scheduled task is owned by this sampler; :meth:`aclose`
        awaits it. Refusals / empty-context samples with no contexts
        are silently dropped — we never evaluate an ungrounded answer.
        """
        if not self.enabled or self._closed:
            return
        if not sample.contexts:
            _log.debug("sampling.skipped: empty_contexts")
            return
        task = asyncio.create_task(self._evaluate_and_write(sample))
        self._tasks.add(task)
        task.add_done_callback(self._tasks.discard)

    async def aclose(self) -> None:
        """Await every scheduled evaluation and shut the sampler down.

        Called from the FastAPI lifespan on shutdown.
        """
        self._closed = True
        pending = list(self._tasks)
        if not pending:
            return
        # gather returns exceptions rather than raising — each task
        # already logs its own failure, so we just want everything to
        # finish before the process exits.
        await asyncio.gather(*pending, return_exceptions=True)

    async def _evaluate_and_write(self, sample: GroundedSample) -> None:
        assert self._evaluator is not None
        try:
            metrics = await self._evaluator.evaluate(sample)
        except Exception:
            _log.warning("sampling.evaluate_failed")
            return

        cleaned: dict[str, float | bool | str] = {"ragas_sampled": True}
        for name in REQUIRED_METRICS:
            value = metrics.get(name)
            if isinstance(value, (int, float)) and not isinstance(value, bool):
                cleaned[f"ragas_{name}"] = float(value)
        if len(cleaned) == 1:
            # No usable metric value — do NOT write "ragas_sampled=True"
            # by itself. That would misrepresent the run as measured.
            _log.warning("sampling.evaluate_returned_no_valid_metrics")
            return
        try:
            await self._metadata_writer(sample.trace_id, cleaned)
        except Exception:
            _log.warning("sampling.metadata_write_failed")


# --- Disabled fallback ------------------------------------------------------


@dataclass(frozen=True)
class _DisabledSampler:
    """No-op sampler used when the evaluator is unavailable."""

    enabled: bool = field(default=False, init=False)

    def should_sample(self) -> bool:
        return False

    async def submit(self, sample: GroundedSample) -> None:
        return None

    async def aclose(self) -> None:
        return None


def build_sampler(
    *,
    sample_rate: float,
    evaluator: RagasEvaluator | None,
    random_source: Callable[[], float] | None = None,
    metadata_writer: MetadataWriter | None = None,
) -> ProductionSampler | _DisabledSampler:
    """Return a real sampler when an evaluator is available, else a no-op."""
    if evaluator is None:
        return _DisabledSampler()
    return ProductionSampler(
        sample_rate=sample_rate,
        evaluator=evaluator,
        random_source=random_source,
        metadata_writer=metadata_writer,
    )


__all__ = [
    "MAX_CONTEXTS",
    "MAX_CONTEXT_CHARS",
    "REQUIRED_METRICS",
    "GroundedSample",
    "MetadataWriter",
    "ProductionSampler",
    "RagasEvaluator",
    "bounded_contexts",
    "build_sample",
    "build_sampler",
]
