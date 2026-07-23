"""FastAPI application contract.

We exercise the app with a fake runtime factory so the tests do not
touch Postgres / MCP / Anthropic. Concretely:

* ``import expense_agent_svc.app`` does not construct clients.
* ``create_app`` returns a :class:`FastAPI`.
* ``/healthz`` succeeds without any external dependency.
* ``/readyz`` reflects lifespan initialisation and never leaks secrets.
* The fake runtime's cleanup runs when the lifespan exits.
* No shared ``BudgetGuard`` is created in the lifespan (Phase 15 owns
  per-request budgets).
* The streaming route is intentionally absent (Phase 15).
"""

from __future__ import annotations

import contextlib
from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from typing import Any

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from expense_agent_svc.app import create_app
from expense_agent_svc.dependencies import AgentDependencies
from expense_agent_svc.runtime import AgentRuntime
from expense_agent_svc.settings import Settings

# ---------- Fake collaborators ----------


class _FakeSession:
    initialized = False

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


@dataclass
class _FakeSaver:
    """Minimal stand-in for AsyncPostgresSaver used only by the app tests.

    We never call any langgraph API on it; the test app does not run
    the compiled graph.
    """


@dataclass
class _FakeCompiledGraph:
    """Minimal stand-in for the compiled LangGraph."""


@dataclass
class _CleanupRecorder:
    entered: int = 0
    exited: int = 0
    events: list[str] = field(default_factory=list)


def _fake_runtime_factory(
    recorder: _CleanupRecorder,
) -> Any:
    """Build a runtime factory whose lifecycle is fully observable."""

    @contextlib.asynccontextmanager
    async def factory(settings: Settings) -> AsyncIterator[AgentRuntime]:
        recorder.entered += 1
        recorder.events.append("enter")
        deps = AgentDependencies(
            settings=settings,
            mcp_session=_FakeSession(),
            anthropic=_FakeClient(),
            instructor=_FakeClient(),
            retrieve=_stub_retrieve,
        )
        runtime = AgentRuntime(
            settings=settings,
            dependencies=deps,
            graph=_FakeCompiledGraph(),  # type: ignore[arg-type]
            checkpointer=_FakeSaver(),  # type: ignore[arg-type]
            ready={"postgres_checkpointer": True, "mcp_session": True, "graph": True},
        )
        try:
            yield runtime
        finally:
            recorder.exited += 1
            recorder.events.append("exit")

    return factory


# ---------- Import-time hermeticity ----------


def test_import_does_not_construct_clients() -> None:
    """``expense_agent_svc.app`` module must not import heavy client
    libraries at the top level.

    Once another test has loaded ``langgraph.checkpoint.postgres.aio``
    or ``anthropic`` the sys.modules probe is not a reliable proxy —
    test ordering would decide the result. Inspect the app source
    directly: any ``import anthropic`` / ``from mcp ...`` /
    ``from langgraph.checkpoint.postgres.aio`` at the top of ``app.py``
    would leak clients into every ``import`` of the module.
    """
    from pathlib import Path

    source = Path("src/expense_agent_svc/app.py").read_text()
    # Everything above ``def create_app`` counts as top-level.
    boundary = source.index("def create_app(")
    top = source[:boundary]
    for forbidden in (
        "from anthropic",
        "import anthropic\n",
        "from mcp ",
        "import mcp\n",
        "from langgraph.checkpoint.postgres.aio",
    ):
        assert forbidden not in top, (
            f"{forbidden!r} appears at the top of app.py — would drag "
            "clients into every module import."
        )
    # And the module still exposes ``create_app`` / ``run``.
    from expense_agent_svc.app import create_app as _create_app
    from expense_agent_svc.app import run as _run

    assert callable(_create_app)
    assert callable(_run)


# ---------- App shape ----------


def test_create_app_returns_fastapi() -> None:
    recorder = _CleanupRecorder()
    app = create_app(runtime_factory=_fake_runtime_factory(recorder), settings=Settings())
    assert isinstance(app, FastAPI)


def test_streaming_route_is_intentionally_absent_in_phase_14() -> None:
    recorder = _CleanupRecorder()
    app = create_app(runtime_factory=_fake_runtime_factory(recorder), settings=Settings())
    paths = {route.path for route in app.routes if hasattr(route, "path")}
    # Phase 15 owns /v1/chat/stream — asserting its absence guards
    # against a lifecycle-first implementation accidentally spilling
    # into Phase 14.
    assert "/v1/chat/stream" not in paths


# ---------- Healthz / readyz ----------


def test_healthz_succeeds_without_dependencies() -> None:
    recorder = _CleanupRecorder()
    app = create_app(runtime_factory=_fake_runtime_factory(recorder), settings=Settings())
    with TestClient(app) as client:
        response = client.get("/healthz")
        assert response.status_code == 200
        payload = response.json()
        assert payload["status"] == "ok"
        assert payload["service"] == "expense-agent-svc"


def test_readyz_reports_not_ready_outside_lifespan() -> None:
    recorder = _CleanupRecorder()
    app = create_app(runtime_factory=_fake_runtime_factory(recorder), settings=Settings())
    # Without entering the TestClient (which triggers the lifespan) the
    # app's state.ready flag is False, so a direct call must 503. We
    # simulate that by peeking at the internal state without a client.
    assert getattr(app.state, "ready", False) is False


def test_readyz_is_ready_inside_lifespan() -> None:
    recorder = _CleanupRecorder()
    app = create_app(runtime_factory=_fake_runtime_factory(recorder), settings=Settings())
    with TestClient(app) as client:
        response = client.get("/readyz")
        assert response.status_code == 200
        payload = response.json()
        assert payload["status"] == "ready"
        components = payload["components"]
        for name in ("postgres_checkpointer", "mcp_session", "graph"):
            assert components[name] is True


def test_readyz_does_not_leak_secrets() -> None:
    """Readiness response must not expose DSNs, tokens, or hostnames."""
    from pydantic import SecretStr

    recorder = _CleanupRecorder()
    tokened = Settings(
        postgres_url="postgresql://user:secretpwd@dbhost.internal:5432/prod",
        mcp_sse_url="https://mcp.internal:8443/sse",
        mcp_bearer_jwt=SecretStr("eyJheHAxYzI.super.jwt"),
        anthropic_api_key=SecretStr("sk-ant-verysecret"),
    )
    app = create_app(runtime_factory=_fake_runtime_factory(recorder), settings=tokened)
    with TestClient(app) as client:
        text = client.get("/readyz").text
    for leak in (
        "secretpwd",
        "eyJheHAxYzI.super.jwt",
        "sk-ant-verysecret",
        "dbhost.internal",
        "mcp.internal",
    ):
        assert leak not in text, f"readyz leaked {leak!r}"


# ---------- Lifespan cleanup ----------


def test_fake_runtime_lifespan_enters_and_exits() -> None:
    recorder = _CleanupRecorder()
    app = create_app(runtime_factory=_fake_runtime_factory(recorder), settings=Settings())
    with TestClient(app):
        # inside the lifespan
        assert recorder.entered == 1
        assert recorder.exited == 0
        assert app.state.runtime is not None
    # after the lifespan exits
    assert recorder.exited == 1
    assert recorder.events == ["enter", "exit"]
    assert app.state.runtime is None
    assert app.state.ready is False


# ---------- BudgetGuard invariant ----------


def test_readyz_returns_503_before_lifespan_boots() -> None:
    """Directly call the /readyz handler while ``app.state.ready`` is False.

    A pod that is coming up (or coming down) must send 503 so a
    load balancer stops routing to it before any incoming request
    can see a half-initialised runtime.
    """
    recorder = _CleanupRecorder()
    app = create_app(runtime_factory=_fake_runtime_factory(recorder), settings=Settings())
    # Do NOT enter TestClient — that would trigger the lifespan.
    client = TestClient(app, raise_server_exceptions=False)
    # TestClient's ASGI ``__enter__`` triggers the lifespan; using
    # ``client.get`` directly without ``with`` re-uses ASGI without
    # the lifespan hooks, so state.ready remains False.
    response = client.get("/readyz")
    assert response.status_code == 503
    assert response.json()["status"] == "not_ready"


def test_create_app_default_runtime_factory_is_the_module_default() -> None:
    """When no runtime_factory is passed, the production factory is wired."""
    # We only need to construct the app — not enter the lifespan.
    # This forces the ``runtime_factory is None`` branch to execute
    # and imports the default factory lazily.
    app = create_app(settings=Settings())
    assert isinstance(app, FastAPI)


def test_run_calls_uvicorn_with_settings(monkeypatch: pytest.MonkeyPatch) -> None:
    """``run()`` composes an app and hands it to uvicorn — verified via a stub."""
    import expense_agent_svc.app as app_module

    calls: list[dict[str, Any]] = []

    def _fake_uvicorn_run(*args: Any, **kwargs: Any) -> None:
        calls.append({"args": args, "kwargs": kwargs})

    # Provide a stub uvicorn.run so we neither bind a port nor start
    # the default runtime factory. Injecting into sys.modules also
    # short-circuits the import inside ``run``.
    import sys
    import types

    fake = types.ModuleType("uvicorn")
    fake.run = _fake_uvicorn_run  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "uvicorn", fake)
    # Provide a runtime_factory-free path: monkeypatch create_app to
    # skip the default factory import so we exercise ``run`` alone.
    monkeypatch.setattr(
        app_module,
        "create_app",
        lambda settings=None: FastAPI(),
    )
    app_module.run()
    assert calls, "uvicorn.run was not invoked"
    kwargs = calls[0]["kwargs"]
    assert kwargs["host"]
    assert isinstance(kwargs["port"], int)


def test_no_budget_guard_created_in_app_or_runtime_modules() -> None:
    """Per-request budgets are owned by Phase 15's request handler.

    Neither the app factory nor the runtime factory may construct a
    :class:`~expense_agent_svc.budgets.BudgetGuard` — sharing one guard
    across requests would let one tenant deny another. We check the
    source directly rather than counting instances at runtime, so the
    invariant survives future refactoring.
    """
    import re
    from pathlib import Path

    for name in ("app.py", "runtime.py"):
        source = Path(f"src/expense_agent_svc/{name}").read_text()
        # Look for ``BudgetGuard(`` — a call — rather than the bare
        # symbol, which appears in type annotations and Protocols.
        assert not re.search(r"\bBudgetGuard\s*\(", source), (
            f"{name} constructs a BudgetGuard; per-request budgets belong to Phase 15"
        )
