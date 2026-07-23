"""AgentState reducer proofs.

Confirm — by inspecting :attr:`AgentState.__annotations__` — that every
reducer-annotated field is present and uses the expected reducer, and
that :func:`_merge_tool_results` preserves both parallel branches.
"""

from __future__ import annotations

import operator
import typing

from langgraph.graph.message import add_messages

from expense_agent_svc.state import (
    AgentState,
    _merge_tool_results,
    initial_state,
)


def _reducer_for(field: str) -> object:
    """Extract the reducer callable from an ``Annotated[...]`` field."""
    hint = typing.get_type_hints(AgentState, include_extras=True)[field]
    args = typing.get_args(hint)
    # Annotated[T, reducer] -> (T, reducer)
    assert len(args) >= 2, f"{field} is not Annotated with a reducer"
    return args[1]


def test_docs_uses_operator_add() -> None:
    assert _reducer_for("docs") is operator.add


def test_cost_uses_operator_add() -> None:
    assert _reducer_for("cost_usd_e5") is operator.add


def test_visited_nodes_uses_operator_add() -> None:
    assert _reducer_for("visited_nodes") is operator.add


def test_errors_uses_operator_add() -> None:
    assert _reducer_for("errors") is operator.add


def test_messages_uses_add_messages() -> None:
    assert _reducer_for("messages") is add_messages


def test_tool_results_uses_merge_reducer() -> None:
    assert _reducer_for("tool_results") is _merge_tool_results


def test_merge_tool_results_preserves_both_branches() -> None:
    # Simulate the supervisor fan-out: retrieval and API both wrote a
    # slice of tool_results in the same super-step.
    left: dict[str, object] = {"orders.get_order": {"order_id": "ord-1"}}
    right: dict[str, object] = {"rag.retrieve": {"docs": 5}}

    merged = _merge_tool_results(left, right)
    assert merged == {
        "orders.get_order": {"order_id": "ord-1"},
        "rag.retrieve": {"docs": 5},
    }
    # And the reducer is not sensitive to ordering: swapping the branches
    # produces the same union.
    assert _merge_tool_results(right, left) == merged


def test_merge_tool_results_preserves_earlier_write_on_key_collision() -> None:
    old: dict[str, object] = {"orders.get_order": {"order_id": "ord-first"}}
    new: dict[str, object] = {"orders.get_order": {"order_id": "ord-second"}}
    merged = _merge_tool_results(old, new)
    assert merged == {"orders.get_order": {"order_id": "ord-first"}}


def test_merge_tool_results_handles_none() -> None:
    assert _merge_tool_results(None, {"k": 1}) == {"k": 1}
    assert _merge_tool_results({"k": 1}, None) == {"k": 1}
    assert _merge_tool_results(None, None) == {}


def test_initial_state_shape() -> None:
    state = initial_state(
        question="Which policy explains meal deductions?",
        tenant_id="tenant-a",
        thread_id="thread-1",
        request_id="req-abc",
    )
    assert state["question"] == "Which policy explains meal deductions?"
    assert state["tenant_id"] == "tenant-a"
    assert state["thread_id"] == "thread-1"
    assert state["request_id"] == "req-abc"
    assert state["docs"] == []
    assert state["tool_results"] == {}
    assert state["cost_usd_e5"] == 0
    assert state["visited_nodes"] == []
    assert state["errors"] == []
    assert state["messages"] == []
    assert state["answer"] is None
    assert state["final_answer"] is None
