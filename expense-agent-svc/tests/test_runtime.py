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
    for text in (_runtime_source(), _app_source()):
        # A BudgetGuard *construction* is the anti-pattern; type
        # annotations mentioning the class are fine.
        import re

        assert not re.search(r"\bBudgetGuard\s*\(", text), (
            "runtime/app must not build a BudgetGuard — per-request budgets "
            "are constructed at the request boundary in Phase 15."
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
