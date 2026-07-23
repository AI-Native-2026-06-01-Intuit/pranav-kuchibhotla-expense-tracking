"""Trajectory + cost + external-RAGAS gate contract.

Cover:

* Exactly 20 scenarios in the committed JSONL.
* Every rubric category is represented across the 20 rows.
* Duplicate qid rejected by the loader.
* Trajectory matcher semantics (docs-only, api-only, both, ordering,
  synthesis-before-worker, duplicate synthesis, missing worker,
  foreign node).
* Threshold failures produce a False gate result.
* Cost regression exactly 15% passes, above 15% fails, zero baseline
  is safe, and a passing gate never overwrites the committed
  baseline.
* External RAGAS: missing key fails without local-skip, local-skip
  reports ``skipped``, injected evaluator >=0.85 passes, <0.85 fails.
* JSON report shape is honest — measured values are numbers, skipped
  values are ``null`` (never a fabricated number).
"""

from __future__ import annotations

import json
from collections.abc import Mapping
from pathlib import Path

import pytest

from evals.trajectory import (
    REQUIRED_SCENARIO_COUNT,
    Scenario,
    ScenarioValidationError,
    answer_substring_match,
    load_scenarios,
    trajectory_match,
)
from expense_agent_svc.sampling import GroundedSample
from expense_agent_svc.scripts.eval import (
    ANSWER_FLOOR,
    COST_REGRESSION_MAX,
    FAITHFULNESS_FLOOR,
    TRAJECTORY_FLOOR,
    Aggregate,
    build_report,
    check_cost_regression,
    gate_pass,
    load_baseline,
    run_deterministic,
    run_external,
)

_HERE = Path(__file__).resolve().parents[1]
_SCENARIOS = _HERE / "evals" / "scenarios.jsonl"
_BASELINE = _HERE / "evals" / "last_run.json"


# ---------- Scenario file contract ----------


def test_scenarios_file_has_exactly_twenty_rows() -> None:
    scenarios = load_scenarios(_SCENARIOS)
    assert len(scenarios) == REQUIRED_SCENARIO_COUNT


def test_scenarios_file_covers_every_rubric_category() -> None:
    scenarios = load_scenarios(_SCENARIOS)
    tenants = {s.tenant_id for s in scenarios}
    assert tenants == {"tenant-a", "tenant-b", "tenant-c"}

    def _kind(s: Scenario) -> str:
        exp = set(s.expected_nodes)
        if "retrieval_agent" in exp and "api_agent" in exp:
            return "both"
        if "api_agent" in exp:
            return "api_only"
        if "retrieval_agent" in exp:
            return "docs_only"
        return "unknown"

    kinds = {_kind(s) for s in scenarios}
    assert "docs_only" in kinds
    assert "api_only" in kinds
    assert "both" in kinds

    # Refusal / unknown-default retrieval trajectory.
    qids = {s.qid for s in scenarios}
    assert any(q.startswith("unknown-") for q in qids)
    assert any(q.startswith("refusal-") for q in qids)
    # Order lookup, refund intent, policy/document, deduction/eligibility.
    assert any(q.startswith("order-") for q in qids)
    assert any(q.startswith("refund-") for q in qids)
    assert any(q.startswith("policy-") for q in qids)
    assert any(q.startswith("eligibility-") for q in qids)
    assert any(q.startswith("combo-") for q in qids)


def test_duplicate_qid_rejected(tmp_path: Path) -> None:
    row = {
        "qid": "dup-1",
        "question": "policy?",
        "tenant_id": "tenant-a",
        "expected_nodes": ["retrieval_agent", "synthesis_agent"],
        "expected_answer_substring": "policy",
    }
    # 20 rows but only 2 unique qids -> duplicate error.
    lines = [json.dumps(row)] * REQUIRED_SCENARIO_COUNT
    path = tmp_path / "dup.jsonl"
    path.write_text("\n".join(lines))
    with pytest.raises(ScenarioValidationError, match="duplicate qid"):
        load_scenarios(path)


def test_wrong_count_rejected(tmp_path: Path) -> None:
    row = {
        "qid": "only-1",
        "question": "policy?",
        "tenant_id": "tenant-a",
        "expected_nodes": ["retrieval_agent", "synthesis_agent"],
        "expected_answer_substring": "policy",
    }
    path = tmp_path / "one.jsonl"
    path.write_text(json.dumps(row))
    with pytest.raises(ScenarioValidationError, match="exactly 20"):
        load_scenarios(path)


def test_unknown_tenant_rejected(tmp_path: Path) -> None:
    row = {
        "qid": "bad-tenant",
        "question": "q",
        "tenant_id": "tenant-zzz",
        "expected_nodes": ["retrieval_agent", "synthesis_agent"],
        "expected_answer_substring": "q",
    }
    path = tmp_path / "bad.jsonl"
    path.write_text(json.dumps(row))
    with pytest.raises(ScenarioValidationError, match="unknown tenant_id"):
        load_scenarios(path)


def test_unknown_node_rejected(tmp_path: Path) -> None:
    row = {
        "qid": "bad-node",
        "question": "q",
        "tenant_id": "tenant-a",
        "expected_nodes": ["retrieval_agent", "not_a_node", "synthesis_agent"],
        "expected_answer_substring": "q",
    }
    path = tmp_path / "bad.jsonl"
    path.write_text(json.dumps(row))
    with pytest.raises(ScenarioValidationError, match="unknown node"):
        load_scenarios(path)


# ---------- Trajectory matcher semantics ----------


def test_docs_only_ordered_match() -> None:
    assert (
        trajectory_match(
            ["retrieval_agent", "synthesis_agent"],
            ["retrieval_agent", "synthesis_agent"],
        )
        == 1.0
    )


def test_api_only_ordered_match() -> None:
    assert (
        trajectory_match(
            ["api_agent", "synthesis_agent"],
            ["api_agent", "synthesis_agent"],
        )
        == 1.0
    )


def test_both_branch_accepts_either_worker_order() -> None:
    # retrieval, api, synthesis
    assert (
        trajectory_match(
            ["retrieval_agent", "api_agent", "synthesis_agent"],
            ["retrieval_agent", "api_agent", "synthesis_agent"],
        )
        == 1.0
    )
    # api, retrieval, synthesis — parallel dispatch swapped order
    assert (
        trajectory_match(
            ["api_agent", "retrieval_agent", "synthesis_agent"],
            ["retrieval_agent", "api_agent", "synthesis_agent"],
        )
        == 1.0
    )


def test_synthesis_before_worker_rejected() -> None:
    assert (
        trajectory_match(
            ["synthesis_agent", "retrieval_agent"],
            ["retrieval_agent", "synthesis_agent"],
        )
        == 0.0
    )


def test_duplicate_synthesis_rejected() -> None:
    assert (
        trajectory_match(
            ["retrieval_agent", "synthesis_agent", "synthesis_agent"],
            ["retrieval_agent", "synthesis_agent"],
        )
        == 0.0
    )


def test_missing_worker_rejected() -> None:
    # expected both retrieval and api, but only retrieval appears.
    assert (
        trajectory_match(
            ["retrieval_agent", "synthesis_agent"],
            ["retrieval_agent", "api_agent", "synthesis_agent"],
        )
        == 0.0
    )


def test_foreign_node_rejected() -> None:
    # A worker that was not expected shows up.
    assert (
        trajectory_match(
            ["retrieval_agent", "api_agent", "synthesis_agent"],
            ["retrieval_agent", "synthesis_agent"],
        )
        == 0.0
    )


def test_empty_inputs_mismatch() -> None:
    assert trajectory_match([], ["retrieval_agent", "synthesis_agent"]) == 0.0
    assert trajectory_match(["retrieval_agent"], []) == 0.0


def test_answer_substring_case_insensitive() -> None:
    assert answer_substring_match("Refund status: SETTLED", "refund") == 1.0
    assert answer_substring_match("nope", "refund") == 0.0
    assert answer_substring_match("policy", "") == 0.0


# ---------- Deterministic runner ----------


def test_deterministic_gate_passes_all_committed_scenarios() -> None:
    scenarios = load_scenarios(_SCENARIOS)
    results, aggregate = run_deterministic(scenarios)
    assert len(results) == REQUIRED_SCENARIO_COUNT
    assert aggregate.source == "deterministic_fixture"
    assert aggregate.trajectory_mean >= TRAJECTORY_FLOOR
    assert aggregate.answer_mean >= ANSWER_FLOOR
    # And all per-scenario matches are 1.0 — no partial credit expected
    # for the committed 20.
    assert all(r.trajectory_match == 1.0 for r in results)
    assert all(r.answer_match == 1.0 for r in results)


# ---------- Cost regression ----------


def test_cost_regression_exactly_15_percent_passes() -> None:
    baseline: Mapping[str, object] = {"mean_cost_usd_e5": 100.0, "source": "deterministic_fixture"}
    aggregate = Aggregate(
        trajectory_mean=1.0, answer_mean=1.0, mean_cost_usd_e5=115.0, scenario_count=20
    )
    result = check_cost_regression(aggregate, baseline)
    assert abs(result.regression - 0.15) < 1e-9
    assert result.passes


def test_cost_regression_above_15_percent_fails() -> None:
    baseline: Mapping[str, object] = {"mean_cost_usd_e5": 100.0, "source": "deterministic_fixture"}
    aggregate = Aggregate(
        trajectory_mean=1.0, answer_mean=1.0, mean_cost_usd_e5=115.001, scenario_count=20
    )
    result = check_cost_regression(aggregate, baseline)
    assert result.regression > COST_REGRESSION_MAX
    assert result.passes is False


def test_cost_regression_zero_baseline_is_safe() -> None:
    baseline: Mapping[str, object] = {"mean_cost_usd_e5": 0.0, "source": "deterministic_fixture"}
    zero = Aggregate(trajectory_mean=1.0, answer_mean=1.0, mean_cost_usd_e5=0.0, scenario_count=20)
    nonzero = Aggregate(
        trajectory_mean=1.0, answer_mean=1.0, mean_cost_usd_e5=1.0, scenario_count=20
    )
    assert check_cost_regression(zero, baseline).passes is True
    assert check_cost_regression(nonzero, baseline).passes is False


def test_committed_baseline_matches_current_deterministic_run() -> None:
    baseline = load_baseline(_BASELINE)
    assert baseline["source"] == "deterministic_fixture", (
        "the committed baseline must be labelled 'deterministic_fixture', "
        "never a measured production cost"
    )
    scenarios = load_scenarios(_SCENARIOS)
    _results, aggregate = run_deterministic(scenarios)
    cost = check_cost_regression(aggregate, baseline)
    # Baseline stability: with no code changes, the committed baseline
    # must equal today's deterministic mean (no drift).
    assert cost.regression == 0.0
    assert cost.passes


def test_ordinary_gate_never_writes_to_committed_baseline(tmp_path: Path) -> None:
    """A passing --gate run must not mutate evals/last_run.json.

    We prove this at the API level: neither run_deterministic nor
    check_cost_regression touch the baseline path — they only read.
    A caller that wants to update the baseline must do so explicitly.
    """
    scenarios = load_scenarios(_SCENARIOS)
    before = _BASELINE.read_bytes()
    _results, aggregate = run_deterministic(scenarios)
    baseline = load_baseline(_BASELINE)
    _cost = check_cost_regression(aggregate, baseline)
    after = _BASELINE.read_bytes()
    assert before == after


# ---------- Gate composition ----------


def test_gate_pass_requires_all_thresholds() -> None:
    good_aggregate = Aggregate(
        trajectory_mean=0.9,
        answer_mean=0.8,
        mean_cost_usd_e5=100.0,
        scenario_count=20,
    )
    baseline: Mapping[str, object] = {"mean_cost_usd_e5": 100.0, "source": "deterministic_fixture"}
    cost = check_cost_regression(good_aggregate, baseline)
    assert gate_pass(good_aggregate, cost, external=None) is True

    bad_trajectory = Aggregate(
        trajectory_mean=0.5,
        answer_mean=0.9,
        mean_cost_usd_e5=100.0,
        scenario_count=20,
    )
    assert gate_pass(bad_trajectory, cost, external=None) is False

    bad_answer = Aggregate(
        trajectory_mean=0.9,
        answer_mean=0.5,
        mean_cost_usd_e5=100.0,
        scenario_count=20,
    )
    assert gate_pass(bad_answer, cost, external=None) is False


# ---------- External RAGAS ----------


class _FakeEvaluator:
    def __init__(self, *, faithfulness: float) -> None:
        self._faithfulness = faithfulness
        self.calls: list[GroundedSample] = []

    async def evaluate(self, sample: GroundedSample) -> Mapping[str, float]:
        self.calls.append(sample)
        return {
            "faithfulness": self._faithfulness,
            "context_recall": self._faithfulness,
            "answer_relevancy": self._faithfulness,
        }


@pytest.mark.asyncio
async def test_external_missing_key_and_no_local_skip_fails() -> None:
    scenarios = load_scenarios(_SCENARIOS)
    result = await run_external(
        scenarios,
        None,
        allow_skip=False,
        credentials_present=False,
    )
    assert result.status == "credentials_missing"
    assert result.faithfulness is None
    assert result.passes is False


@pytest.mark.asyncio
async def test_external_missing_key_with_local_skip_reports_skipped() -> None:
    scenarios = load_scenarios(_SCENARIOS)
    result = await run_external(
        scenarios,
        None,
        allow_skip=True,
        credentials_present=False,
    )
    assert result.status == "skipped"
    assert result.faithfulness is None
    assert "EXPENSE_AGENT_ALLOW_EXTERNAL_EVAL_SKIP" in (result.reason or "")


@pytest.mark.asyncio
async def test_external_fake_evaluator_passes_at_or_above_floor() -> None:
    scenarios = load_scenarios(_SCENARIOS)
    evaluator = _FakeEvaluator(faithfulness=FAITHFULNESS_FLOOR)
    result = await run_external(
        scenarios,
        evaluator,
        allow_skip=False,
        credentials_present=True,
    )
    assert result.status == "measured"
    assert result.faithfulness == FAITHFULNESS_FLOOR
    assert result.passes is True
    # Refusal / unknown-default scenarios are excluded from external
    # scoring — they carry no grounded context. Three such rows exist
    # in the committed set, so 17 scenarios contributed a call.
    assert len(evaluator.calls) == REQUIRED_SCENARIO_COUNT - 3


@pytest.mark.asyncio
async def test_external_fake_evaluator_fails_below_floor() -> None:
    scenarios = load_scenarios(_SCENARIOS)
    evaluator = _FakeEvaluator(faithfulness=0.84)
    result = await run_external(
        scenarios,
        evaluator,
        allow_skip=False,
        credentials_present=True,
    )
    assert result.status == "measured"
    assert result.faithfulness is not None
    assert result.faithfulness < FAITHFULNESS_FLOOR
    assert result.passes is False


# ---------- JSON report honesty ----------


def test_report_honesty_with_skipped_external() -> None:
    scenarios = load_scenarios(_SCENARIOS)
    _results, aggregate = run_deterministic(scenarios)
    baseline = load_baseline(_BASELINE)
    cost = check_cost_regression(aggregate, baseline)

    import asyncio as _asyncio

    external = _asyncio.run(
        run_external(scenarios, None, allow_skip=True, credentials_present=False)
    )
    report = build_report(
        aggregate=aggregate,
        cost=cost,
        external=external,
        trajectory_pass=True,
        answer_pass=True,
    )
    assert isinstance(report, dict)
    ext_field = report["external_ragas"]
    assert isinstance(ext_field, dict)
    assert ext_field["status"] == "skipped"
    # Faithfulness is null (not a fabricated number) when skipped.
    assert ext_field["faithfulness"] is None
    assert ext_field["pass"] is False
    # Report source matches the deterministic fixture label.
    assert report["source"] == "deterministic_fixture"


def test_report_honesty_with_measured_external() -> None:
    scenarios = load_scenarios(_SCENARIOS)
    _results, aggregate = run_deterministic(scenarios)
    baseline = load_baseline(_BASELINE)
    cost = check_cost_regression(aggregate, baseline)

    import asyncio as _asyncio

    external = _asyncio.run(
        run_external(
            scenarios,
            _FakeEvaluator(faithfulness=0.9),
            allow_skip=False,
            credentials_present=True,
        )
    )
    report = build_report(
        aggregate=aggregate,
        cost=cost,
        external=external,
        trajectory_pass=True,
        answer_pass=True,
    )
    ext_field = report["external_ragas"]
    assert isinstance(ext_field, dict)
    assert ext_field["status"] == "measured"
    assert ext_field["faithfulness"] == 0.9
    assert ext_field["pass"] is True
