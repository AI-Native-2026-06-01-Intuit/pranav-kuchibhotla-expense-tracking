"""Supervisor routing contract.

Cover:

* Docs / policy keywords route to ``retrieval_agent``.
* Order / refund / status / ``ord-synth`` route to ``api_agent``.
* Combined prompts fan out to both workers.
* Unknown questions default to retrieval.
* Every branch returns ``list[Send]``.
* Forwarded payload is the minimal request identity, not the full
  accumulated state.
"""

from __future__ import annotations

from langgraph.types import Send

from expense_agent_svc.graph import supervisor
from expense_agent_svc.state import AgentState


def _state(question: str) -> AgentState:
    return AgentState(
        question=question,
        tenant_id="tenant-a",
        thread_id="thread-1",
        request_id="req-1",
        messages=[],
        docs=[],
        tool_results={},
        answer=None,
        final_answer=None,
        cost_usd_e5=0,
        visited_nodes=[],
        errors=[],
    )


def _targets(sends: list[Send]) -> list[str]:
    return [s.node for s in sends]


def test_supervisor_returns_list_of_send() -> None:
    result = supervisor(_state("policy?"))
    assert isinstance(result, list)
    assert all(isinstance(s, Send) for s in result)


def test_docs_only_routes_to_retrieval() -> None:
    for q in [
        "What is the deduction policy for meals?",
        "Show me the docs about eligible expenses.",
        "What rules apply for home office deductions?",
    ]:
        targets = _targets(supervisor(_state(q)))
        assert targets == ["retrieval_agent"], (q, targets)


def test_api_only_routes_to_api() -> None:
    for q in [
        "What is the status of order ord-1234?",
        "Please issue a refund for ord-synth-9001.",
        "Look up ord-synth-9001 status",
    ]:
        targets = _targets(supervisor(_state(q)))
        assert targets == ["api_agent"], (q, targets)


def test_combined_prompt_fans_out_to_both() -> None:
    q = "What is the refund policy for order ord-synth-9001?"
    targets = _targets(supervisor(_state(q)))
    assert set(targets) == {"retrieval_agent", "api_agent"}


def test_unknown_defaults_to_retrieval() -> None:
    targets = _targets(supervisor(_state("hello there")))
    assert targets == ["retrieval_agent"]


def test_forwarded_payload_carries_only_request_identity() -> None:
    state = _state("policy?")
    # A worker should never receive the accumulated docs/tool_results
    # because the reducers already handle that on the fan-in edge.
    sends = supervisor(state)
    payload = sends[0].arg
    assert set(payload.keys()) == {"question", "tenant_id", "thread_id", "request_id"}


def test_supervisor_case_insensitive() -> None:
    # Uppercase order words still match.
    targets = _targets(supervisor(_state("Refund the ORDER please")))
    assert targets == ["api_agent"]
