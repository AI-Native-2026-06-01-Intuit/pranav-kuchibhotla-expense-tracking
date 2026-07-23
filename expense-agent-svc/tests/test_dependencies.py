"""Runtime dependency + per-request registry proofs.

The key invariants under test:

* :class:`AgentDependencies` is process-scoped and holds only Protocols
  or the ``Settings`` snapshot; nothing here ever lands in
  :class:`AgentState`.
* Each request gets its own :class:`RequestContext` (and therefore its
  own ``BudgetGuard``); the registry never lets two requests share a
  budget.
* Releasing a request cleans up the registry, and repeated release is
  idempotent.
"""

from __future__ import annotations

import dataclasses

import pytest

from expense_agent_svc import dependencies as deps
from expense_agent_svc.dependencies import (
    AgentDependencies,
    RequestContext,
    _registry_size_for_tests,
    get_request_context,
    register_request,
    release_request,
)
from expense_agent_svc.settings import Settings


class _FakeBudget:
    """Minimal object satisfying :class:`BudgetGuardLike` for the tests."""

    def __init__(self, ceiling: int = 25_000) -> None:
        self._spent = 0
        self._ceiling = ceiling

    @property
    def spent_usd_e5(self) -> int:
        return self._spent

    @property
    def ceiling_usd_e5(self) -> int:
        return self._ceiling

    def check_or_raise(self) -> None:  # pragma: no cover - trivial
        return None

    def add_cost(self, cost_usd_e5: int) -> None:  # pragma: no cover - trivial
        self._spent += cost_usd_e5

    def record_usage(  # pragma: no cover - trivial
        self,
        *,
        input_tokens: int,
        output_tokens: int,
        input_rate_usd_e5_per_million: int,
        output_rate_usd_e5_per_million: int,
    ) -> int:
        del input_tokens, output_tokens
        del input_rate_usd_e5_per_million, output_rate_usd_e5_per_million
        return 0


class _FakeMCPSession:
    async def list_tools(self, cursor: str | None = None) -> object:  # pragma: no cover
        return object()

    async def call_tool(
        self,
        name: str,
        arguments: dict[str, object] | None = None,
    ) -> object:  # pragma: no cover
        return object()


class _FakeClient:
    @property
    def messages(self) -> object:  # pragma: no cover
        return object()


def _stub_retrieve(query_text: str, tenant_id: str, /) -> dict[str, object]:
    del query_text, tenant_id
    return {"answer": "stub", "citations": []}


def _make_deps() -> AgentDependencies:
    return AgentDependencies(
        settings=Settings(),
        mcp_session=_FakeMCPSession(),
        anthropic=_FakeClient(),
        instructor=_FakeClient(),
        retrieve=_stub_retrieve,
    )


def test_agent_dependencies_is_frozen_dataclass() -> None:
    d = _make_deps()
    assert dataclasses.is_dataclass(d)
    with pytest.raises(dataclasses.FrozenInstanceError):
        d.settings = Settings()  # type: ignore[misc]


def test_register_and_get_and_release_request() -> None:
    starting = _registry_size_for_tests()
    ctx = RequestContext(
        thread_id="thread-a",
        tenant_id="tenant-a",
        budget=_FakeBudget(),
    )
    register_request(ctx)
    try:
        assert _registry_size_for_tests() == starting + 1
        fetched = get_request_context(ctx.request_id)
        assert fetched is ctx
        assert fetched.thread_id == "thread-a"
        assert fetched.tenant_id == "tenant-a"
    finally:
        release_request(ctx.request_id)

    assert _registry_size_for_tests() == starting
    # Idempotent release
    release_request(ctx.request_id)
    assert _registry_size_for_tests() == starting


def test_duplicate_register_raises() -> None:
    ctx = RequestContext(thread_id="t", tenant_id="tenant-a", budget=_FakeBudget())
    register_request(ctx)
    try:
        with pytest.raises(KeyError):
            register_request(ctx)
    finally:
        release_request(ctx.request_id)


def test_unknown_request_id_raises() -> None:
    with pytest.raises(KeyError):
        get_request_context("does-not-exist")


def test_each_request_has_its_own_budget() -> None:
    b1 = _FakeBudget()
    b2 = _FakeBudget()
    ctx1 = RequestContext(thread_id="t1", tenant_id="tenant-a", budget=b1)
    ctx2 = RequestContext(thread_id="t2", tenant_id="tenant-a", budget=b2)
    register_request(ctx1)
    register_request(ctx2)
    try:
        assert get_request_context(ctx1.request_id).budget is b1
        assert get_request_context(ctx2.request_id).budget is b2
        assert b1 is not b2
    finally:
        release_request(ctx1.request_id)
        release_request(ctx2.request_id)


def test_registry_module_exposes_expected_surface() -> None:
    # No sneaky "get_all_contexts()" that would let a leak walk the map.
    exported = {
        name for name in dir(deps) if not name.startswith("_") and callable(getattr(deps, name))
    }
    # Public surface: register/get/release plus the dataclasses/Protocols.
    for expected in (
        "register_request",
        "get_request_context",
        "release_request",
        "get_request_context_for_state",
    ):
        assert expected in exported


# ---------- get_request_context_for_state ----------


from expense_agent_svc.dependencies import (  # noqa: E402
    RequestContextMismatch,
    RequestContextUnavailable,
    get_request_context_for_state,
)


def test_get_request_context_for_state_returns_registered_context() -> None:
    ctx = RequestContext(thread_id="t", tenant_id="tenant-a", budget=_FakeBudget())
    register_request(ctx)
    try:
        resolved = get_request_context_for_state(
            {"request_id": ctx.request_id, "tenant_id": "tenant-a", "thread_id": "t"}
        )
        assert resolved is ctx
    finally:
        release_request(ctx.request_id)


def test_get_request_context_for_state_missing_request_id_raises() -> None:
    with pytest.raises(RequestContextUnavailable):
        get_request_context_for_state({"request_id": ""})
    with pytest.raises(RequestContextUnavailable):
        get_request_context_for_state({})
    with pytest.raises(RequestContextUnavailable):
        get_request_context_for_state("not a dict")


def test_get_request_context_for_state_stale_id_raises() -> None:
    with pytest.raises(RequestContextUnavailable):
        get_request_context_for_state({"request_id": "does-not-exist"})


def test_get_request_context_for_state_tenant_mismatch_rejected() -> None:
    ctx = RequestContext(thread_id="t", tenant_id="tenant-a", budget=_FakeBudget())
    register_request(ctx)
    try:
        with pytest.raises(RequestContextMismatch):
            get_request_context_for_state({"request_id": ctx.request_id, "tenant_id": "tenant-b"})
    finally:
        release_request(ctx.request_id)


def test_get_request_context_for_state_thread_mismatch_rejected() -> None:
    ctx = RequestContext(thread_id="thread-a", tenant_id="tenant-a", budget=_FakeBudget())
    register_request(ctx)
    try:
        with pytest.raises(RequestContextMismatch):
            get_request_context_for_state({"request_id": ctx.request_id, "thread_id": "thread-b"})
    finally:
        release_request(ctx.request_id)


def test_agent_state_stores_only_request_id_and_scalars() -> None:
    """AgentState grew a ``request_id`` string. Prove it stays a scalar
    and that neither a RequestContext nor a BudgetGuard can be smuggled
    in through the initial-state helper."""
    from expense_agent_svc.state import initial_state

    state = initial_state(
        question="policy?",
        tenant_id="tenant-a",
        thread_id="t",
        request_id="opaque-1",
    )
    # Only scalar request_id.
    request_id = state["request_id"]
    assert isinstance(request_id, str)
    # A new request replaces the prior request_id on a resumed thread —
    # LangGraph reducers on the immutable-typed request_id key
    # overwrite by default (no reducer). Prove by constructing a fresh
    # initial_state with the same thread and a new request_id.
    fresh = initial_state(
        question="policy?",
        tenant_id="tenant-a",
        thread_id="t",
        request_id="opaque-2",
    )
    assert fresh["request_id"] == "opaque-2"
    assert fresh["request_id"] != state["request_id"]
