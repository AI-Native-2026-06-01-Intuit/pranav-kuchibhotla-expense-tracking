"""Trajectory dataclass, loader, and ordered-sequence matcher.

The 20 committed scenarios live in :file:`scenarios.jsonl` — one JSON
object per line. The loader normalises them into :class:`Scenario`
frozen dataclasses and validates:

* exactly 20 rows,
* no duplicate ``qid``,
* every ``expected_nodes`` entry is one of the three worker names or
  ``synthesis_agent``,
* tenant is one of ``tenant-a/b/c``,
* an optional ``expected_tool`` string.

The matcher is intentionally strict on ordering:

* docs-only  -> retrieval_agent must appear before synthesis_agent.
* API-only   -> api_agent must appear before synthesis_agent.
* both       -> both workers must appear before synthesis_agent, in
  either order (parallel dispatch is nondeterministic).
* Exactly one ``synthesis_agent`` must appear at the end.
* Unexpected extra nodes fail the match.
"""

from __future__ import annotations

import json
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from pathlib import Path

REQUIRED_SCENARIO_COUNT = 20
_ALLOWED_TENANTS = frozenset({"tenant-a", "tenant-b", "tenant-c"})
_ALLOWED_NODES = frozenset({"retrieval_agent", "api_agent", "synthesis_agent"})


@dataclass(frozen=True)
class Scenario:
    """One committed trajectory scenario."""

    qid: str
    question: str
    tenant_id: str
    expected_nodes: tuple[str, ...]
    expected_answer_substring: str
    expected_tool: str | None = None


class ScenarioValidationError(ValueError):
    """Raised when :func:`load_scenarios` finds an ill-formed JSONL file."""


def _validate_scenario(index: int, raw: Mapping[str, object]) -> Scenario:
    for required in (
        "qid",
        "question",
        "tenant_id",
        "expected_nodes",
        "expected_answer_substring",
    ):
        if required not in raw:
            raise ScenarioValidationError(f"row {index}: missing required field {required!r}")
    qid = raw["qid"]
    if not isinstance(qid, str) or not qid:
        raise ScenarioValidationError(f"row {index}: qid must be a non-empty string")
    question = raw["question"]
    if not isinstance(question, str) or not question:
        raise ScenarioValidationError(f"row {index}: question must be non-empty")
    tenant = raw["tenant_id"]
    if tenant not in _ALLOWED_TENANTS:
        raise ScenarioValidationError(f"row {index}: unknown tenant_id {tenant!r}")
    nodes = raw["expected_nodes"]
    if not isinstance(nodes, list) or not nodes:
        raise ScenarioValidationError(f"row {index}: expected_nodes must be a non-empty list")
    for node in nodes:
        if node not in _ALLOWED_NODES:
            raise ScenarioValidationError(
                f"row {index}: expected_nodes contains unknown node {node!r}"
            )
    substring = raw["expected_answer_substring"]
    if not isinstance(substring, str):
        raise ScenarioValidationError(f"row {index}: expected_answer_substring must be a string")
    tool = raw.get("expected_tool")
    if tool is not None and not isinstance(tool, str):
        raise ScenarioValidationError(f"row {index}: expected_tool must be null or a string")
    return Scenario(
        qid=qid,
        question=question,
        tenant_id=str(tenant),
        expected_nodes=tuple(str(n) for n in nodes),
        expected_answer_substring=substring,
        expected_tool=tool,
    )


def load_scenarios(path: str | Path) -> tuple[Scenario, ...]:
    """Read and validate ``scenarios.jsonl`` — returns the 20 rows."""
    source = Path(path)
    if not source.exists():
        raise ScenarioValidationError(f"scenarios file not found: {source}")

    scenarios: list[Scenario] = []
    seen_qids: set[str] = set()
    for index, line in enumerate(source.read_text().splitlines(), start=1):
        stripped = line.strip()
        if not stripped:
            continue
        try:
            raw = json.loads(stripped)
        except json.JSONDecodeError as exc:
            raise ScenarioValidationError(f"row {index}: invalid JSON: {exc}") from exc
        if not isinstance(raw, Mapping):
            raise ScenarioValidationError(f"row {index}: not a JSON object")
        scenario = _validate_scenario(index, raw)
        if scenario.qid in seen_qids:
            raise ScenarioValidationError(f"duplicate qid: {scenario.qid!r}")
        seen_qids.add(scenario.qid)
        scenarios.append(scenario)

    if len(scenarios) != REQUIRED_SCENARIO_COUNT:
        raise ScenarioValidationError(
            f"expected exactly {REQUIRED_SCENARIO_COUNT} scenarios, found {len(scenarios)}"
        )
    return tuple(scenarios)


# --- Trajectory matching ----------------------------------------------------


def _first_index_of(seq: Iterable[str], target: str) -> int:
    for i, value in enumerate(seq):
        if value == target:
            return i
    return -1


def trajectory_match(
    actual: Iterable[str],
    expected: Iterable[str],
) -> float:
    """Return 1.0 if ``actual`` satisfies ``expected`` in order, else 0.0.

    Rules:

    * Every node named in ``expected`` must appear in ``actual``.
    * ``actual`` may not contain any node **not** listed in
      ``expected`` (foreign nodes are a mismatch).
    * ``synthesis_agent`` must appear exactly once and must come last.
    * When ``expected`` names both worker nodes (retrieval + api),
      they may appear in either order — but both must appear before
      the terminal ``synthesis_agent``.
    * When ``expected`` names a single worker node, that node must
      appear before the terminal ``synthesis_agent``.
    """
    actual_list = list(actual)
    expected_list = list(expected)

    if not actual_list or not expected_list:
        return 0.0
    if set(actual_list) != set(expected_list):
        return 0.0
    if actual_list.count("synthesis_agent") != 1:
        return 0.0
    # synthesis_agent must be last.
    if actual_list[-1] != "synthesis_agent":
        return 0.0
    workers = [n for n in expected_list if n != "synthesis_agent"]
    for worker in workers:
        idx = _first_index_of(actual_list, worker)
        if idx < 0:
            return 0.0
        # worker must be before synthesis_agent (which is at [-1]).
        if idx >= len(actual_list) - 1:
            return 0.0
    return 1.0


def answer_substring_match(answer: str, substring: str) -> float:
    """Return 1.0 if ``substring`` (case-insensitive) is in ``answer``."""
    if not substring:
        return 0.0
    return 1.0 if substring.lower() in answer.lower() else 0.0


__all__ = [
    "REQUIRED_SCENARIO_COUNT",
    "Scenario",
    "ScenarioValidationError",
    "answer_substring_match",
    "load_scenarios",
    "trajectory_match",
]
