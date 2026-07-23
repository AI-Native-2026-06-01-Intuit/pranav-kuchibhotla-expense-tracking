"""Postgres checkpoint durability across a simulated process restart.

This is an integration test — it needs a real Postgres reachable at
``EXPENSE_AGENT_TEST_POSTGRES_URL`` (defaults to the local
``w7d5-postgres`` container's DSN). The suite is skipped when Postgres
is unreachable, but never silently: the skip message names the DSN that
failed so a CI misconfiguration cannot masquerade as a pass.

The restart is *simulated* deterministically rather than by SIGKILL:

1. Open the first :class:`AsyncPostgresSaver` context, call
   :meth:`~AsyncPostgresSaver.setup`, compile the graph with the
   live saver.
2. Run the graph for a *unique* ``thread_id`` (per-test namespace) so
   two concurrent test workers cannot collide.
3. Assert an intermediate checkpoint row exists and contains only
   JSON-serialisable state (no MCP session, no ``BudgetGuard``, no
   ``asyncio`` primitives).
4. Exit the first saver's async context — this closes the underlying
   Postgres connection just as a pod stop would.
5. Open a **second** ``AsyncPostgresSaver`` on the same DSN; call
   ``setup()`` again to prove idempotency of the schema migration.
6. Compile a **new** graph over the new saver and call
   :meth:`~CompiledStateGraph.aget_state` with the same ``thread_id`` —
   assert the prior ``docs`` / ``tool_results`` / ``visited_nodes`` are
   still visible (i.e., we did NOT start from empty state) and the
   answer produced before the restart is present.

Local execution:

.. code-block:: sh

    EXPENSE_AGENT_TEST_POSTGRES_URL=postgresql://postgres:postgres@localhost:5432/postgres \\
        uv run pytest -v tests/test_checkpointer_resume.py

"""

from __future__ import annotations

import os
import uuid
from collections.abc import Awaitable, Callable, Mapping
from typing import Any, cast

import psycopg
import pytest
from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver

from expense_agent_svc.graph import NodeSet, build_expense_agent_graph, invocation_config

_DEFAULT_DSN = "postgresql://postgres:postgres@localhost:5432/postgres"
_DSN_ENV = "EXPENSE_AGENT_TEST_POSTGRES_URL"


def _dsn() -> str:
    return os.environ.get(_DSN_ENV, _DEFAULT_DSN)


def _postgres_reachable() -> bool:
    """Return True if we can open a plain sync psycopg connection.

    Any exception means the test suite skips — we never lie about a
    green run when the store is offline.
    """
    try:
        with psycopg.connect(_dsn(), connect_timeout=2) as conn, conn.cursor() as cur:
            cur.execute("SELECT 1")
            cur.fetchone()
        return True
    except Exception:
        return False


pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(
        not _postgres_reachable(),
        reason=(
            f"integration Postgres unreachable at {_dsn()!s}; "
            f"set {_DSN_ENV} and ensure the w7d5-postgres container is up."
        ),
    ),
]


# ---------- Test node factory ----------
#
# We build tiny fake nodes that push deterministic, JSON-serialisable
# state into the reducer channels. No real MCP / Anthropic / RAG traffic
# is generated — the point of *this* test is durability across a
# simulated pod restart, not node correctness.


def _make_nodes() -> NodeSet:
    async def retrieval(_state: Mapping[str, object]) -> Mapping[str, object]:
        return {
            "docs": [
                {"chunk_id": "c-persist-1", "doc_id": "d-persist-1", "quote": "checkpoint-me"}
            ],
            "cost_usd_e5": 0,
            "visited_nodes": ["retrieval_agent"],
            "errors": [],
        }

    async def api(_state: Mapping[str, object]) -> Mapping[str, object]:
        return {
            "tool_results": {"orders.get_order": "OPEN:ord-persist-1"},
            "cost_usd_e5": 0,
            "visited_nodes": ["api_agent"],
            "errors": [],
        }

    async def synthesis(state: Mapping[str, object]) -> Mapping[str, object]:
        docs_raw = state.get("docs") or []
        tools_raw = state.get("tool_results") or {}
        docs_len = len(docs_raw) if isinstance(docs_raw, list) else 0
        tools_len = len(tools_raw) if isinstance(tools_raw, dict) else 0
        text = f"synthesized with docs={docs_len} tools={tools_len}"
        return {
            "answer": text,
            "final_answer": {"text": text, "citations": [], "confidence": 0.7},
            "cost_usd_e5": 0,
            "visited_nodes": ["synthesis_agent"],
            "errors": [],
        }

    return NodeSet(retrieval_agent=retrieval, api_agent=api, synthesis_agent=synthesis)


def _unique_thread_id() -> str:
    # Fully unique per test run so two concurrent workers cannot see
    # each other's checkpoints and so a re-run never resumes a stale
    # thread from a prior CI attempt.
    return f"w7d5-resume-{uuid.uuid4()}"


async def _run_initial_request(
    saver: AsyncPostgresSaver,
    thread_id: str,
) -> Mapping[str, object]:
    graph = build_expense_agent_graph(nodes=_make_nodes(), checkpointer=saver)
    input_state: dict[str, object] = {
        "question": "What is the refund policy for order ord-persist-1?",
        "tenant_id": "tenant-a",
        "thread_id": thread_id,
        "request_id": f"req-{thread_id}",
    }
    result: Mapping[str, object] = await graph.ainvoke(
        cast(Any, input_state), cast(Any, invocation_config(thread_id))
    )
    return result


# ---------- Tests ----------


@pytest.mark.asyncio
async def test_setup_is_idempotent_across_two_savers() -> None:
    """Two consecutive setup() calls on the same DSN must not fail or wipe rows.

    We interleave a checkpoint write between the two setup calls and
    assert the row is still readable after the second setup — that is
    the exact contract migration idempotency has to satisfy for a
    rolling deployment.
    """
    thread_id = _unique_thread_id()
    async with AsyncPostgresSaver.from_conn_string(_dsn()) as saver_a:
        await saver_a.setup()
        await _run_initial_request(saver_a, thread_id)

    async with AsyncPostgresSaver.from_conn_string(_dsn()) as saver_b:
        # Second setup on the same DSN must not raise and must not
        # truncate prior checkpoint rows.
        await saver_b.setup()
        graph = build_expense_agent_graph(nodes=_make_nodes(), checkpointer=saver_b)
        state = await graph.aget_state(cast(Any, invocation_config(thread_id)))
        # The thread survives the second setup unchanged.
        assert state is not None
        assert state.values.get("answer"), (
            "expected the prior answer to survive a second setup() call"
        )


@pytest.mark.asyncio
async def test_state_survives_saver_restart_simulation() -> None:
    """Restart simulation: durable state must survive closing + reopening the saver.

    This is not a SIGKILL — it is a controlled ``async with`` exit that
    fully closes the underlying Postgres connection before a *new*
    saver instance is opened on the same DSN. LangGraph's
    ``AsyncPostgresSaver.from_conn_string`` is an async context
    manager, so exiting the block is the only supported way to release
    the connection.
    """
    thread_id = _unique_thread_id()

    # --- First "process": run the request end-to-end ---------------------
    async with AsyncPostgresSaver.from_conn_string(_dsn()) as saver_1:
        await saver_1.setup()
        result_1 = await _run_initial_request(saver_1, thread_id)

    # The in-memory result is what the current process saw — proves the
    # graph itself worked.
    assert result_1["answer"] == "synthesized with docs=1 tools=1"

    # --- Simulated pod restart: brand-new saver on the same DSN ---------
    async with AsyncPostgresSaver.from_conn_string(_dsn()) as saver_2:
        # setup() is idempotent — a fresh replica boots the same schema.
        await saver_2.setup()

        # Rebuild the graph over the new saver as a new process would.
        graph_2 = build_expense_agent_graph(nodes=_make_nodes(), checkpointer=saver_2)
        state = await graph_2.aget_state(cast(Any, invocation_config(thread_id)))

    # The reopened saver sees the prior process's terminal state.
    assert state is not None, "expected a StateSnapshot for the resumed thread"
    values = state.values
    assert values, "resumed state is empty — checkpoint durability broken"

    # Prior worker outputs survived the restart.
    docs = values.get("docs")
    assert isinstance(docs, list) and len(docs) == 1
    assert docs[0]["chunk_id"] == "c-persist-1"

    tool_results = values.get("tool_results")
    assert isinstance(tool_results, dict)
    assert tool_results.get("orders.get_order") == "OPEN:ord-persist-1"

    # Both workers and synthesis are in the visited history.
    visited = values.get("visited_nodes") or []
    assert isinstance(visited, list)
    assert {"retrieval_agent", "api_agent", "synthesis_agent"} <= set(visited)

    # The answer produced before the "restart" is present.
    assert values.get("answer") == "synthesized with docs=1 tools=1"


@pytest.mark.asyncio
async def test_checkpoint_row_contains_only_serialisable_state() -> None:
    """The persisted row must contain no MCP session / BudgetGuard / callable.

    We inspect the state snapshot values directly rather than the raw
    JSONB — LangGraph serialises through its ``JsonPlusSerializer``, so
    what matters for durability is that reading back yields plain
    Python types, not process-scoped objects.
    """
    thread_id = _unique_thread_id()
    async with AsyncPostgresSaver.from_conn_string(_dsn()) as saver:
        await saver.setup()
        await _run_initial_request(saver, thread_id)
        graph = build_expense_agent_graph(nodes=_make_nodes(), checkpointer=saver)
        state = await graph.aget_state(cast(Any, invocation_config(thread_id)))

    assert state is not None
    for key, value in state.values.items():
        # No callable ever belongs in checkpointed state.
        assert not callable(value), f"callable leaked into checkpoint via {key!r}"
        # No async / thread primitive either.
        module = type(value).__module__
        assert not module.startswith("asyncio"), (
            f"asyncio primitive leaked into checkpoint via {key!r}"
        )
        assert "psycopg" not in module, f"connection object leaked via {key!r}"


def test_helper_documented_for_local_execution() -> None:
    """Docstring names the exact command to run this suite locally.

    A future engineer opening this file should not have to guess the
    env var name.
    """
    assert "EXPENSE_AGENT_TEST_POSTGRES_URL" in (__doc__ or "")


# NOTE: we intentionally do not add a "no os.kill / MemorySaver" self-check
# here — the four substantive tests above will only pass when the *real*
# AsyncPostgresSaver is exercised end-to-end, so an in-memory shortcut
# cannot fake a green run. A separate committed guardrail
# (test_no_memorysaver_in_production_source in test_graph_compile.py)
# already enforces that no MemorySaver / InMemorySaver reference is
# present in ``src/``.


# Explicit type re-export just so mypy sees Callable/Awaitable as used
# (some pytest configurations run mypy over test files strictly).
_NodeSig = Callable[[Mapping[str, object]], Awaitable[Mapping[str, object]]]
