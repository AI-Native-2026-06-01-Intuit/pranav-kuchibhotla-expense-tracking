"""Three-agent supervisor graph.

Topology:

    START -> supervisor (conditional) -> [retrieval_agent | api_agent | both]
                                                  |
                                            synthesis_agent (exactly once)
                                                  |
                                                 END

The supervisor returns ``list[Send]`` so LangGraph 1.2's parallel
dispatch can fan out to both workers when the question needs both
branches. A dedicated ``supervisor`` START-node exists so the fan-in on
``synthesis_agent`` respects LangGraph's default channel-join
semantics (both worker nodes flow to synthesis via direct edges, and
LangGraph joins them on that step boundary — so synthesis runs exactly
once even in the "both" branch).

Installed API adaptations (recorded in Phase 1):

* ``StateGraph.compile()`` does **not** accept ``recursion_limit`` in
  LangGraph 1.2. That limit is a *runtime* invocation option. Every
  call site (invoke / ainvoke / astream_events) must build its config
  through :func:`invocation_config` — this module owns the single
  helper so a `grep` will confirm no call site omits it.
* ``PostgresSaver.from_conn_string(...)`` is a context manager (see
  Phase 12). This builder accepts an already-opened checkpointer as a
  parameter; it does not open / close any Postgres connection itself.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, cast

from langgraph.graph import END, START, StateGraph
from langgraph.types import Send

from .state import AgentState

if TYPE_CHECKING:
    from langgraph.checkpoint.base import BaseCheckpointSaver
    from langgraph.graph.state import CompiledStateGraph

DEFAULT_RECURSION_LIMIT = 25

# --- Supervisor keyword routing ------------------------------------------------

# Retrieval-flavoured keywords: documentation, deduction / eligibility
# knowledge, policy questions.
_RETRIEVAL_KEYWORDS = frozenset(
    {
        "policy",
        "document",
        "documents",
        "docs",
        "rule",
        "rules",
        "deduction",
        "deductible",
        "eligible",
        "eligibility",
        "knowledge",
    }
)

# API-flavoured keywords: order/refund actions on the ledger. The W7D4
# synthetic id prefix ``ord-synth-`` is here so a question like "look up
# ord-synth-9001" routes to the API branch even without the word
# "order".
_API_KEYWORDS = frozenset({"order", "orders", "refund", "refunds", "status"})
_API_TOKENS = ("ord-synth",)


def _needs_retrieval(text: str) -> bool:
    lowered = text.lower()
    return any(word in lowered for word in _RETRIEVAL_KEYWORDS)


def _needs_api(text: str) -> bool:
    lowered = text.lower()
    if any(tok in lowered for tok in _API_TOKENS):
        return True
    tokens = set(_tokenize(lowered))
    return bool(tokens & _API_KEYWORDS)


def _tokenize(text: str) -> list[str]:
    out: list[str] = []
    current = []
    for ch in text:
        if ch.isalnum() or ch == "-":
            current.append(ch)
        else:
            if current:
                out.append("".join(current))
                current = []
    if current:
        out.append("".join(current))
    return out


def supervisor(state: AgentState) -> list[Send]:
    """Route the request to the right worker(s).

    Returns ``list[Send]`` so LangGraph can fan out in parallel when
    both branches are needed. Rules:

    * docs / policy keywords -> retrieval_agent
    * order / refund / status / ``ord-synth`` -> api_agent
    * both -> both workers in the same super-step (reducers preserve
      their combined output)
    * unknown -> default to retrieval (documentation is the safer
      grounding surface than a stateful ledger call)

    Future policy centre-of-mass — this docstring intentionally names
    the concerns that will land here next so they have exactly one
    home: **tenant gates**, **per-tenant rate limits**, **request
    budget routing** (deferring expensive branches when budget is near
    the ceiling), and **human-in-the-loop / approval hooks** on write
    tools.
    """
    question = str(state.get("question", ""))
    forwarded = _forwarded_payload(state)

    docs_needed = _needs_retrieval(question)
    api_needed = _needs_api(question)

    if docs_needed and api_needed:
        return [
            Send("retrieval_agent", forwarded),
            Send("api_agent", forwarded),
        ]
    if api_needed:
        return [Send("api_agent", forwarded)]
    if docs_needed:
        return [Send("retrieval_agent", forwarded)]
    # Default: retrieval is the safer grounding surface for an
    # unknown question than an API side-effect.
    return [Send("retrieval_agent", forwarded)]


def _forwarded_payload(state: AgentState) -> dict[str, object]:
    """Return a minimal payload the workers need — just the request identity.

    We do not fan out the full accumulated state because reducers on
    the target keys already merge the workers' partial writes. Forwarding
    a mutable copy of ``docs``/``tool_results`` would confuse the
    reducer with duplicate elements.
    """
    return {
        "question": state.get("question", ""),
        "tenant_id": state.get("tenant_id", ""),
        "thread_id": state.get("thread_id", ""),
        "request_id": state.get("request_id", ""),
    }


# --- Invocation config ---------------------------------------------------------


def invocation_config(thread_id: str) -> dict[str, object]:
    """Central runtime config used by every graph invocation.

    Contains:

    * ``configurable.thread_id`` — required for checkpoint routing
    * ``recursion_limit`` = :data:`DEFAULT_RECURSION_LIMIT` (25) —
      LangGraph 1.2 accepts this only at invocation time, not on
      ``compile()``.

    Every call site (invoke / ainvoke / astream_events) must build its
    config through this helper.
    """
    if not thread_id:
        raise ValueError("thread_id must be non-empty")
    return {
        "configurable": {"thread_id": thread_id},
        "recursion_limit": DEFAULT_RECURSION_LIMIT,
    }


# --- Graph builder -------------------------------------------------------------

NodeCallable = Callable[[Mapping[str, object]], Awaitable[Mapping[str, object]]]


@dataclass(frozen=True)
class NodeSet:
    """Injected node bodies.

    Tests build fakes; the FastAPI lifespan builds real ones via
    ``make_retrieval_agent`` / ``make_api_agent`` / ``make_synthesis_agent``.
    """

    retrieval_agent: NodeCallable
    api_agent: NodeCallable
    synthesis_agent: NodeCallable


def build_expense_agent_graph(
    *,
    nodes: NodeSet,
    checkpointer: BaseCheckpointSaver[Any] | None = None,
) -> CompiledStateGraph[AgentState, Any, AgentState, AgentState]:
    """Assemble and compile the three-agent supervisor graph.

    ``checkpointer`` is passed through to :meth:`StateGraph.compile` and
    can be ``None`` for unit tests. In production it is the
    :class:`~langgraph.checkpoint.postgres.AsyncPostgresSaver` opened by
    the FastAPI lifespan (Phase 12); this function does not open or
    close any Postgres connection.
    """
    builder: StateGraph[AgentState, Any, AgentState, AgentState] = StateGraph(AgentState)
    # LangGraph 1.2's overload set for add_node is very strict about the
    # node-input generic; our nodes are ``Callable[[Mapping[str, object]]``,
    # which is a supertype of AgentState. Cast at the boundary rather than
    # loosening the node signature (nodes stay Mapping-based so tests can
    # feed plain dicts).
    builder.add_node("retrieval_agent", cast(Any, nodes.retrieval_agent))
    builder.add_node("api_agent", cast(Any, nodes.api_agent))
    builder.add_node("synthesis_agent", cast(Any, nodes.synthesis_agent))

    # Conditional START -> supervisor -> Send(s).
    builder.add_conditional_edges(
        START,
        supervisor,
        ["retrieval_agent", "api_agent"],
    )
    # Both workers flow into synthesis. LangGraph joins both writers on
    # the target-node boundary within the same super-step, so synthesis
    # executes exactly once even when both workers ran.
    builder.add_edge("retrieval_agent", "synthesis_agent")
    builder.add_edge("api_agent", "synthesis_agent")
    builder.add_edge("synthesis_agent", END)

    return builder.compile(checkpointer=checkpointer)


__all__ = [
    "DEFAULT_RECURSION_LIMIT",
    "NodeSet",
    "build_expense_agent_graph",
    "invocation_config",
    "supervisor",
]
