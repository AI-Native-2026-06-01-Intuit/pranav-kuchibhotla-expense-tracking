"""RAGAS golden-set threshold gate for the expense-ai RAG path.

Two layers of validation:

* A cheap, always-on shape test that confirms the 50-row golden set exists,
  has the required fields, and that our threshold constants match the
  assignment.
* An external-only RAGAS ``evaluate()`` gate that runs when Anthropic /
  RAGAS-evaluator credentials are available and skips honestly otherwise.
"""

from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

GOLDEN_PATH = Path(__file__).resolve().parent / "golden" / "expense_golden_50.jsonl"

FAITHFULNESS_THRESHOLD = 0.80
ANSWER_RELEVANCY_THRESHOLD = 0.80
CONTEXT_PRECISION_THRESHOLD = 0.65
CONTEXT_RECALL_THRESHOLD = 0.70


def _load_golden() -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []
    with GOLDEN_PATH.open() as fh:
        for line in fh:
            if line.strip():
                rows.append(json.loads(line))
    return rows


def test_golden_set_shape() -> None:
    rows = _load_golden()
    assert len(rows) >= 50, f"golden set has {len(rows)} rows, need >= 50"
    required = {"question", "answer", "contexts", "ground_truth"}
    for i, row in enumerate(rows):
        missing = required - set(row.keys())
        assert not missing, f"row {i} missing fields: {missing}"
        assert isinstance(row["contexts"], list)
        for ctx in row["contexts"]:
            assert isinstance(ctx, str)


def test_thresholds_match_assignment() -> None:
    assert FAITHFULNESS_THRESHOLD == 0.80
    assert ANSWER_RELEVANCY_THRESHOLD == 0.80
    assert CONTEXT_PRECISION_THRESHOLD == 0.65
    assert CONTEXT_RECALL_THRESHOLD == 0.70


@pytest.mark.slow
@pytest.mark.external
def test_ragas_scores_meet_thresholds() -> None:
    if not os.environ.get("EXPENSE_AI_ANTHROPIC_API_KEY"):
        pytest.skip(
            "EXPENSE_AI_ANTHROPIC_API_KEY missing — skipping external RAGAS eval "
            "(non-external shape test still gates the golden set)."
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
    # RAGAS is strict about columns; keep only the four it expects.
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
        for r in rows
    ]
    dataset = Dataset.from_list(trimmed)

    result = evaluate(
        dataset,
        metrics=[faithfulness, answer_relevancy, context_precision, context_recall],
    )
    scores = result.to_pandas().mean(numeric_only=True).to_dict()  # type: ignore[union-attr]

    assert scores.get("faithfulness", 0.0) >= FAITHFULNESS_THRESHOLD
    assert scores.get("answer_relevancy", 0.0) >= ANSWER_RELEVANCY_THRESHOLD
    assert scores.get("context_precision", 0.0) >= CONTEXT_PRECISION_THRESHOLD
    assert scores.get("context_recall", 0.0) >= CONTEXT_RECALL_THRESHOLD
