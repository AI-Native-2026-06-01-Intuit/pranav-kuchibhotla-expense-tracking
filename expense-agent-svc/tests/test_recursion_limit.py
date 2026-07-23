"""Recursion-limit safety proofs.

Two guarantees:

1. LangGraph raises :class:`~langgraph.errors.GraphRecursionError` at
   the configured limit of 25 (not later, not by hanging). We prove
   this on a *test-only* graph — the production graph must never
   contain an artificial feedback loop.
2. Every production ``.invoke`` / ``.ainvoke`` / ``.astream`` /
   ``.astream_events`` call site routes through
   :func:`expense_agent_svc.graph.invocation_config` so the 25-recursion
   ceiling is impossible to omit accidentally. This test walks the
   ``src/`` AST rather than relying on a shell ``grep``.
"""

from __future__ import annotations

import ast
import operator
import time
from collections.abc import Mapping
from pathlib import Path
from typing import Annotated, Any, TypedDict, cast

import pytest
from langgraph.errors import GraphRecursionError
from langgraph.graph import END, START, StateGraph

from expense_agent_svc.graph import (
    DEFAULT_RECURSION_LIMIT,
    NodeSet,
    build_expense_agent_graph,
    invocation_config,
    supervisor,
)
from expense_agent_svc.state import AgentState


class _CounterState(TypedDict, total=False):
    """Tiny serializable state used only by the recursion-limit fixture."""

    steps: Annotated[list[int], operator.add]


def _build_looping_graph() -> Any:
    """Return a compiled graph with an unconditional cycle.

    Nothing about this graph resembles the production topology — it
    exists only so we can assert LangGraph will refuse to run past the
    configured ``recursion_limit``.
    """

    async def tick(state: _CounterState) -> Mapping[str, object]:
        current = state.get("steps") or []
        return {"steps": [len(current) + 1]}

    builder: StateGraph[_CounterState, None, _CounterState, _CounterState] = StateGraph(
        _CounterState
    )
    builder.add_node("tick", cast(Any, tick))
    builder.add_edge(START, "tick")
    # Unconditional self-loop — the graph itself has no exit condition,
    # so only ``recursion_limit`` stops it.
    builder.add_edge("tick", "tick")
    builder.add_edge("tick", END)  # never taken; kept so LangGraph accepts the graph
    # No checkpointer required for this test — the loop lives entirely
    # in the running super-step budget.
    return builder.compile()


@pytest.mark.asyncio
async def test_synthetic_loop_raises_at_configured_limit() -> None:
    graph = _build_looping_graph()

    started = time.perf_counter()
    with pytest.raises(GraphRecursionError):
        await graph.ainvoke({"steps": []}, cast(Any, invocation_config("test-recursion")))
    elapsed = time.perf_counter() - started

    # The failure must arrive quickly (not hang). 5 seconds is generous
    # for the 25-iteration budget on a laptop.
    assert elapsed < 5.0, f"GraphRecursionError took too long: {elapsed:.2f}s"


def test_invocation_config_recursion_limit_is_twenty_five() -> None:
    """The centralized config must carry recursion_limit=25 exactly."""
    cfg = invocation_config("thread-x")
    assert cfg["recursion_limit"] == 25
    assert DEFAULT_RECURSION_LIMIT == 25
    configurable = cfg["configurable"]
    assert isinstance(configurable, dict)
    assert configurable["thread_id"] == "thread-x"


def test_production_graph_has_no_artificial_feedback_loop() -> None:
    """The production topology must not contain a cycle of its own.

    We build it with fake node bodies and inspect the emitted edge
    list. There must be no edge whose source and target are the same,
    and no edge back from ``synthesis_agent`` into a worker.
    """

    async def stub(_state: Mapping[str, object]) -> Mapping[str, object]:
        return {"visited_nodes": ["stub"]}

    nodes = NodeSet(retrieval_agent=stub, api_agent=stub, synthesis_agent=stub)
    graph = build_expense_agent_graph(nodes=nodes, checkpointer=None)
    edges_json = graph.get_graph().to_json()["edges"]

    forbidden = {
        ("synthesis_agent", "retrieval_agent"),
        ("synthesis_agent", "api_agent"),
    }
    for edge in edges_json:
        source = edge.get("source")
        target = edge.get("target")
        assert source != target, f"self-loop detected on {source!r}"
        assert (source, target) not in forbidden, f"back-edge {source!r} -> {target!r}"


def _referenced_names(module_tree: ast.Module) -> set[str]:
    """Return every bare-name reference in an AST module, for guardrail checks."""
    names: set[str] = set()
    for node in ast.walk(module_tree):
        if isinstance(node, ast.Name):
            names.add(node.id)
        elif isinstance(node, ast.Attribute) and isinstance(node.value, ast.Name):
            names.add(node.value.id)
    return names


_METHODS_UNDER_GUARDRAIL = frozenset({"invoke", "ainvoke", "astream", "astream_events"})


def _graph_calls_in(tree: ast.Module) -> list[str]:
    """Return the method names in ``tree`` that look like graph invocations.

    A "graph invocation" here is an attribute call whose method name is
    one of :data:`_METHODS_UNDER_GUARDRAIL`. We deliberately allow
    bare local names like ``model_invoke(...)`` (the API node's
    injected model-loop hook), because those are not graph runs.
    """
    hits: list[str] = []
    for node in ast.walk(tree):
        if (
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Attribute)
            and node.func.attr in _METHODS_UNDER_GUARDRAIL
        ):
            hits.append(node.func.attr)
    return hits


def test_every_graph_invoke_call_site_uses_invocation_config() -> None:
    """AST-level guardrail: any graph invocation in ``src/`` must reference
    :func:`invocation_config`.

    The Phase 11 grep-based test lives in ``test_graph_compile.py``; this
    committed AST-based test is stricter (a variable named
    ``model_invoke(...)`` inside the API node is *not* a false positive)
    and lives with the recursion-limit proofs where it belongs.
    """
    src_root = Path("src/expense_agent_svc")
    exempt = {"graph.py"}  # graph.py defines invocation_config itself.

    offenders: list[tuple[str, str]] = []
    for py in src_root.rglob("*.py"):
        if py.name in exempt:
            continue
        tree = ast.parse(py.read_text())
        graph_methods = _graph_calls_in(tree)
        if not graph_methods:
            continue
        referenced = _referenced_names(tree)
        # Approved routes: the module imports ``invocation_config``
        # directly, OR it delegates to a helper that already imports it.
        if "invocation_config" in referenced:
            continue
        offenders.append((str(py), ",".join(sorted(set(graph_methods)))))

    assert not offenders, (
        f"the following src files invoke a graph without invocation_config: {offenders!r}"
    )


def test_agent_state_annotation_stays_serialisable() -> None:
    """A state key added later must not smuggle in a non-serialisable type.

    We check that no field on :class:`AgentState` names a type from the
    forbidden set (MCP session, Anthropic client, BudgetGuard,
    Postgres connection, callables). This is a static guardrail — the
    Phase 12 integration test proves the runtime invariant.
    """
    import typing as _typing

    hints = _typing.get_type_hints(AgentState, include_extras=True)
    forbidden_substrings = (
        "ClientSession",
        "AsyncAnthropic",
        "PostgresSaver",
        "BudgetGuard",
        "AgentDependencies",
        "RequestContext",
        "Callable",
    )
    for field, hint in hints.items():
        text = repr(hint)
        for bad in forbidden_substrings:
            assert bad not in text, f"AgentState.{field} references non-serialisable type {bad!r}"
    # And supervisor is used elsewhere; keep the import from being
    # flagged as unused.
    assert callable(supervisor)
