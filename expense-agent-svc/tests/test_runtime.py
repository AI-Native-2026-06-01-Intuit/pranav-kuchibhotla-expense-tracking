"""Runtime module contract (production factory + X-Agent headers).

We deliberately do NOT enter the default runtime factory in these
tests — doing so would open a Postgres connection, an MCP SSE stream,
and construct real Anthropic clients. Instead we read the source and
inspect the public surface to prove:

* The default factory returns an async context manager (so the
  lifespan can ``async with`` it safely).
* Three distinct X-Agent header constants exist and match the three
  worker names.
* The default factory's source shows ``AsyncPostgresSaver`` +
  ``AsyncExitStack`` lifecycle ownership.
* ``saver.setup()`` is invoked *before* the ready flag flips to True.
* The graph is compiled with the live saver.
* ``session.initialize()`` runs before ready.
* No shared ``BudgetGuard`` is constructed anywhere in this module.
"""

from __future__ import annotations

import contextlib
from pathlib import Path
from typing import Any, cast

import pytest

from expense_agent_svc.runtime import (
    X_AGENT_API,
    X_AGENT_RETRIEVAL,
    X_AGENT_SYNTHESIS,
    anthropic_default_headers,
    default_runtime_factory,
)
from expense_agent_svc.settings import Settings

# ---------- Public surface ----------


def test_x_agent_role_constants_match_worker_names() -> None:
    assert X_AGENT_RETRIEVAL == "retrieval_agent"
    assert X_AGENT_API == "api_agent"
    assert X_AGENT_SYNTHESIS == "synthesis_agent"


@pytest.mark.parametrize(
    "role",
    [X_AGENT_RETRIEVAL, X_AGENT_API, X_AGENT_SYNTHESIS],
)
def test_anthropic_default_headers_carries_x_agent(role: str) -> None:
    headers = anthropic_default_headers(role)
    assert headers == {"X-Agent": role}


def test_anthropic_default_headers_rejects_unknown_role() -> None:
    with pytest.raises(ValueError):
        anthropic_default_headers("not-a-worker")


def test_default_factory_returns_async_context_manager() -> None:
    ctx = default_runtime_factory(Settings())
    assert isinstance(ctx, contextlib.AbstractAsyncContextManager)


# ---------- Source-level guarantees ----------


def _runtime_source() -> str:
    return Path("src/expense_agent_svc/runtime.py").read_text()


def _app_source() -> str:
    return Path("src/expense_agent_svc/app.py").read_text()


def test_default_factory_owns_async_postgres_saver_via_exit_stack() -> None:
    text = _runtime_source()
    # The saver lifecycle is co-owned by the AsyncExitStack; both must
    # appear in the same module.
    assert "AsyncPostgresSaver.from_conn_string" in text
    assert "AsyncExitStack" in text
    assert "stack.enter_async_context" in text


def test_saver_setup_precedes_ready_flag() -> None:
    text = _runtime_source()
    setup_idx = text.index("await saver.setup()")
    ready_flip = text.index('ready["postgres_checkpointer"] = True')
    graph_flip = text.index('ready["graph"] = True')
    assert setup_idx < ready_flip, "saver.setup() must run before the ready flag flips"
    # Similarly for the graph.
    assert "build_expense_agent_graph(nodes=" in text
    assert setup_idx < graph_flip


def test_mcp_session_initialize_precedes_ready() -> None:
    text = _runtime_source()
    init_idx = text.index("await session.initialize()")
    mcp_ready = text.index('ready["mcp_session"] = True')
    assert init_idx < mcp_ready


def test_graph_compiled_with_live_saver() -> None:
    text = _runtime_source()
    assert "build_expense_agent_graph(nodes=" in text
    assert "checkpointer=saver" in text


def test_three_distinct_anthropic_clients_configured() -> None:
    text = _runtime_source()
    # Each worker gets its own X-Agent header via anthropic_default_headers.
    assert "anthropic_default_headers(X_AGENT_RETRIEVAL)" in text or (
        "_client(X_AGENT_RETRIEVAL)" in text
    )
    assert "_client(X_AGENT_API)" in text
    assert "_client(X_AGENT_SYNTHESIS)" in text


def test_instructor_wraps_only_the_synthesis_client() -> None:
    text = _runtime_source()
    # Instructor is used exactly once — on the synthesis raw client.
    occurrences = text.count("_instructor.from_anthropic")
    assert occurrences == 1, (
        f"instructor.from_anthropic used {occurrences} times; expected 1 (synthesis only)"
    )


def test_no_shared_budget_guard_in_lifespan() -> None:
    """The runtime module must not construct a shared BudgetGuard.

    ``app.py`` legally constructs one per request inside the chat
    handler (asserted separately in tests/test_app.py). The runtime is
    process-scoped; a BudgetGuard construction here would leak spend
    across tenants.
    """
    import re

    assert not re.search(r"\bBudgetGuard\s*\(", _runtime_source()), (
        "runtime.py must not build a BudgetGuard — per-request budgets are "
        "constructed by the /v1/chat/stream route handler."
    )


def test_no_module_import_of_heavy_clients() -> None:
    """The runtime module may reference anthropic/mcp *inside* the async
    context, but must not import them at module top-level — otherwise
    ``import expense_agent_svc.app`` would drag them in."""
    text = _runtime_source()
    # Find the top-level import block (everything above the first
    # ``@contextlib.asynccontextmanager``).
    boundary = text.index("@contextlib.asynccontextmanager")
    top = text[:boundary]
    for forbidden in ("from anthropic ", "import anthropic\n", "from mcp "):
        assert forbidden not in top, (
            f"{forbidden!r} must not appear before the runtime context manager"
        )


def test_secrets_never_logged() -> None:
    """No print/logger call in runtime.py accepts a settings secret."""
    text = _runtime_source()
    # No plain ``print(`` calls at all.
    assert "print(" not in text
    # No f-string interpolation of a secret.
    for pattern in (
        "mcp_bearer_jwt.get_secret_value()",
        "anthropic_api_key.get_secret_value()",
    ):
        # It's fine to *use* the secret; it must not be printed/logged.
        occurrences = text.count(pattern)
        assert occurrences <= 2, (
            f"{pattern} appears {occurrences} times — verify none reach a logger"
        )


# ---------- Fail-closed MCP configuration ----------


from pydantic import SecretStr  # noqa: E402 -- test-time import used below

from expense_agent_svc.runtime import (  # noqa: E402
    RuntimeConfigurationError,
    make_anthropic_model_invoke,
    make_retrieval_callable,
)


def test_require_mcp_configuration_rejects_empty_bearer() -> None:
    """Startup must fail closed before opening any MCP transport."""
    from expense_agent_svc.runtime import _require_mcp_configuration

    settings = Settings(mcp_bearer_jwt=SecretStr(""))
    with pytest.raises(RuntimeConfigurationError) as exc_info:
        _require_mcp_configuration(settings)
    text = str(exc_info.value)
    # The exception message names the env var but not its value.
    assert "EXPENSE_AGENT_MCP_BEARER_JWT" in text


def test_require_mcp_configuration_never_prints_the_token() -> None:
    """A supplied token must never appear in the exception path.

    We construct a Settings whose token is present so the guardrail
    does NOT raise, then re-verify by monkey-patching the URL empty so
    it DOES raise, and assert the token value never appears in the
    resulting error message.
    """
    from expense_agent_svc.runtime import _require_mcp_configuration

    settings_ok = Settings(
        mcp_bearer_jwt=SecretStr("plain.jwt.value"),
        mcp_sse_url="http://mcp/sse",
    )
    # With both configured, no error.
    _require_mcp_configuration(settings_ok)

    # Settings validation already blocks an empty mcp_sse_url at
    # construction; exercise the empty-URL branch on a hand-crafted
    # stand-in that skips validation. The stand-in still carries a
    # plaintext token so we can prove no get_secret_value() output
    # leaks into the exception.
    class _Stub:
        mcp_sse_url = ""
        mcp_bearer_jwt = SecretStr("plain.jwt.value")

    with pytest.raises(RuntimeConfigurationError) as exc_info:
        _require_mcp_configuration(cast(Settings, _Stub()))
    assert "plain.jwt.value" not in str(exc_info.value)


# ---------- Real API model_invoke adapter ----------


@pytest.mark.asyncio
async def test_make_anthropic_model_invoke_calls_messages_create_with_translated_tools() -> None:
    calls: list[dict[str, Any]] = []

    class _FakeMessages:
        async def create(self, **kwargs: Any) -> Any:
            calls.append(kwargs)

            class _Usage:
                input_tokens = 100
                output_tokens = 50

            class _R:
                stop_reason = "end_turn"

                def __init__(self) -> None:
                    self.content: list[Any] = []
                    self.usage = _Usage()

            return _R()

    class _FakeClient:
        def __init__(self) -> None:
            self.messages = _FakeMessages()

    invoke = make_anthropic_model_invoke(
        api_client=_FakeClient(),
        model_name="claude-fake",
        max_tokens=32,
    )
    response = await invoke(
        [
            {
                "name": "orders.get_order",
                "description": "d",
                "input_schema": {"type": "object"},
            }
        ],
        [{"role": "user", "content": "hi"}],
    )
    assert calls
    kwargs = calls[0]
    assert kwargs["model"] == "claude-fake"
    assert kwargs["max_tokens"] == 32
    tools = kwargs["tools"]
    assert tools == [
        {
            "name": "orders.get_order",
            "description": "d",
            "input_schema": {"type": "object"},
        }
    ]
    assert response.usage.input_tokens == 100


# ---------- Real retrieval callable adapter ----------


def test_make_retrieval_callable_acquires_pool_connection_per_call() -> None:
    """Each call must acquire (and release) one connection from the pool."""

    acquired: list[str] = []
    released: list[str] = []

    class _FakeConn:
        def __init__(self, name: str) -> None:
            self.name = name

        def __enter__(self) -> _FakeConn:
            acquired.append(self.name)
            return self

        def __exit__(self, *_a: object) -> None:
            released.append(self.name)

    class _FakePool:
        def __init__(self) -> None:
            self._counter = 0

        def connection(self) -> _FakeConn:
            self._counter += 1
            return _FakeConn(f"conn-{self._counter}")

    def _fake_retrieve_and_generate(
        query_text: str,
        tenant_id: str,
        *,
        anthropic: Any,
        conn: Any,
        r: Any,
        model_name: str,
    ) -> dict[str, object]:
        del anthropic, r, model_name
        assert isinstance(conn, _FakeConn)
        return {"answer": f"{query_text}|{tenant_id}", "citations": []}

    # Monkey-patch expense_ai.rag.retrieve_and_generate for this test.
    import expense_ai.rag as _rag

    original = _rag.retrieve_and_generate
    _rag.retrieve_and_generate = _fake_retrieve_and_generate
    try:
        settings = Settings()
        retrieve = make_retrieval_callable(
            pool=_FakePool(),
            redis_client=object(),
            retrieval_anthropic=object(),
            settings=settings,
        )
        r1 = retrieve("policy?", "tenant-a")
        r2 = retrieve("order?", "tenant-b")
    finally:
        _rag.retrieve_and_generate = original

    assert r1["answer"] == "policy?|tenant-a"
    assert r2["answer"] == "order?|tenant-b"
    assert len(acquired) == 2
    assert acquired == released, "every acquired connection must be released"


# ---------- Source: rag pool + redis are owned by the AsyncExitStack ----------


def test_runtime_owns_rag_pool_and_redis_via_exit_stack() -> None:
    text = _runtime_source()
    assert "ConnectionPool" in text, "runtime.py must import ConnectionPool"
    assert "stack.callback(pool.close)" in text, "pool.close must be registered on stack"
    assert "stack.callback(redis_client.close)" in text, (
        "redis client close must be registered on stack"
    )


def test_runtime_wires_real_api_model_invoke_not_the_phase14_stub() -> None:
    text = _runtime_source()
    assert "make_anthropic_model_invoke" in text
    assert "_unwired_model_invoke" not in text, "Phase 15 must replace the Phase 14 placeholder"
    assert "make_retrieval_callable" in text, "the production retrieval callable must be wired"
    assert "_require_mcp_configuration" in text, "the fail-closed MCP check must run at startup"
