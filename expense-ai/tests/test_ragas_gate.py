"""W7D3 RAGAS faithfulness gate on the 15-row representative subset.

Per the W7D3 cohort amendment, RAGAS ``evaluate()`` is run on a 15-row
deterministic subset sampled from the 50-row W7D2 golden set. The 50-row
shape gate remains untouched — this file only adds the smaller evaluation
window used for CI gating.

Skip / fail policy:
  * In CI (``CI=true`` in the environment) the gate MUST run for real. A
    missing Anthropic/OpenAI key or a provider workspace-cap / bad-request
    response is a hard failure — never a silent skip.
  * Locally, developers can opt into skipping with
    ``EXPENSE_AI_ALLOW_EXTERNAL_SKIP=1`` when the evaluator key is missing
    or the shared workspace is capped. Without that opt-in the local run
    also fails, so the default developer experience matches CI.
  * ``ragas`` / ``datasets`` import errors always skip (dependency install
    problem, not a scoring problem).

Faithfulness < 0.85 raises SystemExit to halt CI; other metrics assert at
softer floors. No score is ever synthesised.
"""

from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

GOLDEN_PATH = Path(__file__).resolve().parent / "golden" / "expense_golden_50.jsonl"
EVAL_SUBSET_SIZE = 15

FAITHFULNESS_GATE = 0.85
ANSWER_RELEVANCY_FLOOR = 0.80
CONTEXT_PRECISION_FLOOR = 0.75
CONTEXT_RECALL_FLOOR = 0.80


def _load_golden() -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []
    with GOLDEN_PATH.open() as fh:
        for line in fh:
            if line.strip():
                rows.append(json.loads(line))
    return rows


def _deterministic_subset(rows: list[dict[str, object]], n: int) -> list[dict[str, object]]:
    """Evenly spaced deterministic sample so the subset is reproducible."""
    if n >= len(rows):
        return rows
    step = len(rows) / n
    return [rows[int(i * step)] for i in range(n)]


def test_golden_set_min_size() -> None:
    rows = _load_golden()
    assert len(rows) >= 50, f"golden set has {len(rows)} rows, need >= 50"


def test_ragas_thresholds_constants() -> None:
    assert FAITHFULNESS_GATE == 0.85
    assert ANSWER_RELEVANCY_FLOOR == 0.80
    assert CONTEXT_PRECISION_FLOOR == 0.75
    assert CONTEXT_RECALL_FLOOR == 0.80


def test_eval_subset_size_is_fifteen() -> None:
    assert EVAL_SUBSET_SIZE == 15


def test_eval_subset_is_deterministic() -> None:
    rows = _load_golden()
    a = _deterministic_subset(rows, EVAL_SUBSET_SIZE)
    b = _deterministic_subset(rows, EVAL_SUBSET_SIZE)
    assert a == b
    assert len(a) == EVAL_SUBSET_SIZE


def test_eval_subset_row_shape() -> None:
    rows = _load_golden()
    subset = _deterministic_subset(rows, EVAL_SUBSET_SIZE)
    required = {"question", "answer", "contexts", "ground_truth"}
    for i, row in enumerate(subset):
        missing = required - set(row.keys())
        assert not missing, f"subset row {i} missing {missing}"


def _in_ci() -> bool:
    """GitHub Actions and most CI runners set ``CI=true``."""
    return os.environ.get("CI", "").lower() in {"1", "true", "yes"}


def _allow_local_skip() -> bool:
    return os.environ.get("EXPENSE_AI_ALLOW_EXTERNAL_SKIP", "").lower() in {"1", "true", "yes"}


@pytest.mark.slow
@pytest.mark.external
def test_ragas_faithfulness_meets_gate() -> None:
    api_key = os.environ.get("EXPENSE_AI_ANTHROPIC_API_KEY") or os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        msg = (
            "EXPENSE_AI_ANTHROPIC_API_KEY / ANTHROPIC_API_KEY missing — "
            "RAGAS faithfulness gate requires a real evaluator key."
        )
        if _in_ci():
            pytest.fail(f"{msg} CI must run this gate for real (no silent skip).")
        if _allow_local_skip():
            pytest.skip(f"{msg} Local skip allowed via EXPENSE_AI_ALLOW_EXTERNAL_SKIP=1.")
        pytest.fail(
            f"{msg} Set EXPENSE_AI_ALLOW_EXTERNAL_SKIP=1 to skip locally, "
            "or export the key to run the gate."
        )

    try:  # pragma: no cover - external dependency
        from datasets import Dataset
        from ragas import evaluate
        from ragas.metrics import (
            answer_relevancy,
            context_precision,
            context_recall,
            faithfulness,
        )
    except ImportError as exc:  # pragma: no cover - only when deps missing
        pytest.skip(f"ragas/datasets import failed: {exc}")

    rows = _load_golden()
    subset = _deterministic_subset(rows, EVAL_SUBSET_SIZE)
    trimmed = [
        {
            "question": r["question"],
            "answer": r["answer"],
            "contexts": (
                r["contexts"]
                if isinstance(r["contexts"], list) and r["contexts"]
                else ["(no context available)"]
            ),
            "ground_truth": r["ground_truth"],
        }
        for r in subset
    ]
    dataset = Dataset.from_list(trimmed)

    try:  # pragma: no cover - external
        result = evaluate(
            dataset,
            metrics=[faithfulness, answer_relevancy, context_precision, context_recall],
        )
    except Exception as exc:  # pragma: no cover - external
        msg = str(exc).lower()
        provider_soft_failure = any(
            fragment in msg
            for fragment in (
                "usage cap",
                "workspace",
                "rate limit",
                "credential",
                "quota",
                "badrequest",
                "openai",
            )
        )
        if provider_soft_failure:
            if _in_ci():
                pytest.fail(
                    f"RAGAS evaluator returned a provider error in CI: {exc}. "
                    "Not silently skipping — fix the credential / workspace cap."
                )
            if _allow_local_skip():
                pytest.skip(
                    f"RAGAS evaluator unavailable ({exc}); local skip allowed via "
                    "EXPENSE_AI_ALLOW_EXTERNAL_SKIP=1."
                )
        raise

    scores = result.to_pandas().mean(numeric_only=True).to_dict()  # type: ignore[union-attr]

    faithfulness_score = float(scores.get("faithfulness", 0.0))
    if faithfulness_score < FAITHFULNESS_GATE:
        raise SystemExit(f"Faithfulness {faithfulness_score:.3f} below gate {FAITHFULNESS_GATE}")

    assert float(scores.get("answer_relevancy", 0.0)) >= ANSWER_RELEVANCY_FLOOR
    assert float(scores.get("context_precision", 0.0)) >= CONTEXT_PRECISION_FLOOR
    assert float(scores.get("context_recall", 0.0)) >= CONTEXT_RECALL_FLOOR
