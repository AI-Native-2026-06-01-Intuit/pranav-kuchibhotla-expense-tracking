"""Serializable :class:`AgentState` for the three-node supervisor graph.

Design constraints (non-negotiable):

* Everything in :class:`AgentState` must be JSON/pickle-serializable so
  the :class:`~langgraph.checkpoint.postgres.PostgresSaver` can persist
  and resume checkpoints across pod restarts.
* No MCP sessions, Anthropic clients, Postgres pools, ``BudgetGuard``
  instances, or callables belong in state — those live in
  :mod:`expense_agent_svc.dependencies`.
* Every field that can be written by more than one graph node needs an
  explicit reducer. LangGraph resolves parallel writes to the same key
  by invoking the reducer; without one, later writes silently clobber
  earlier ones and the fan-out branches lose data.

The reducers below intentionally match the ordering guarantees the
supervisor and the fan-out API expose. Docs, tool results, cost, visited
nodes, and errors are all accumulated, never overwritten.
"""

from __future__ import annotations

import operator
from typing import Annotated, NotRequired, TypedDict

from langchain_core.messages import BaseMessage
from langgraph.graph.message import add_messages


def _merge_tool_results(
    old: dict[str, object] | None,
    new: dict[str, object] | None,
) -> dict[str, object]:
    """Merge two ``tool_results`` snapshots without losing parallel writes.

    Both branches of the supervisor fan-out (retrieval and API) may write
    to ``tool_results`` in the same super-step. LangGraph will call this
    reducer with both partial dicts. Keys from ``new`` win only when
    ``old`` did not already contain them — this preserves earlier writes
    from a re-entry / retry path — but any distinct key from either side
    is kept.

    ``None`` values are tolerated to match LangGraph's initial-state
    behavior where a missing key can come in as ``None``.
    """
    if not old:
        return dict(new or {})
    if not new:
        return dict(old)
    merged: dict[str, object] = dict(old)
    for key, value in new.items():
        # Preserve the earlier write for the same key (idempotency-friendly).
        merged.setdefault(key, value)
    return merged


class AgentState(TypedDict, total=False):
    """Serializable state carried through the LangGraph supervisor.

    Only the ``question``, ``tenant_id``, and ``thread_id`` are required
    at invocation. Everything else is accumulated by the graph.
    """

    # --- Request identity (required at invoke time) ---
    question: str
    tenant_id: str
    thread_id: str

    # --- Chat messages: LangGraph's canonical add_messages reducer ---
    messages: Annotated[list[BaseMessage], add_messages]

    # --- Retrieval branch output ---
    docs: Annotated[list[dict[str, object]], operator.add]

    # --- API branch output; custom merger tolerates parallel writes ---
    tool_results: Annotated[dict[str, object], _merge_tool_results]

    # --- Synthesis branch output ---
    answer: NotRequired[str | None]
    final_answer: NotRequired[dict[str, object] | None]

    # --- Observability + accounting ---
    cost_usd_e5: Annotated[int, operator.add]
    visited_nodes: Annotated[list[str], operator.add]
    errors: Annotated[list[str], operator.add]


def initial_state(*, question: str, tenant_id: str, thread_id: str) -> AgentState:
    """Return the minimal valid state for a new invocation.

    Consumers should build the invocation input through this helper so
    the reducer-annotated fields start with the right empty collections
    (``list``/``dict``/``0``) — LangGraph's ``operator.add`` reducer
    fails if it is asked to add ``None`` to a list.
    """
    return AgentState(
        question=question,
        tenant_id=tenant_id,
        thread_id=thread_id,
        messages=[],
        docs=[],
        tool_results={},
        answer=None,
        final_answer=None,
        cost_usd_e5=0,
        visited_nodes=[],
        errors=[],
    )
