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
from typing import Any, cast

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


class _FakeCompiledGraph:
    """Minimal stand-in for the compiled LangGraph.

    Exposes ``astream_events`` returning a scriptable event sequence so
    the /v1/chat/stream route can be exercised end-to-end without
    LangGraph / Postgres / Anthropic.
    """

    def __init__(self, events: list[dict[str, Any]] | None = None) -> None:
        self.events = events or [
            {
                "event": "on_chain_end",
                "name": "synthesis_agent",
                "metadata": {"langgraph_node": "synthesis_agent"},
                "data": {
                    "output": {
                        "answer": "fake ok",
                        "final_answer": {
                            "text": "fake ok",
                            "citations": [],
                            "confidence": 0.7,
                        },
                        "visited_nodes": ["synthesis_agent"],
                        "errors": [],
                    }
                },
            }
        ]
        self.received_config: dict[str, object] | None = None
        self.received_input: dict[str, object] | None = None

    def astream_events(
        self,
        input_state: object,
        config: object,
        *,
        version: str,
    ) -> AsyncIterator[dict[str, Any]]:
        self.received_input = cast(dict[str, object], input_state)
        self.received_config = cast(dict[str, object], config)
        assert version == "v2"
        events = list(self.events)

        async def _gen() -> AsyncIterator[dict[str, Any]]:
            for ev in events:
                yield ev

        return _gen()


@dataclass
class _CleanupRecorder:
    entered: int = 0
    exited: int = 0
    events: list[str] = field(default_factory=list)


def _fake_runtime_factory(
    recorder: _CleanupRecorder,
    *,
    graph: _FakeCompiledGraph | None = None,
) -> Any:
    """Build a runtime factory whose lifecycle is fully observable."""
    graph_instance = graph if graph is not None else _FakeCompiledGraph()

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
            graph=cast(Any, graph_instance),
            checkpointer=cast(Any, _FakeSaver()),
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


def test_streaming_route_is_registered_in_phase_15() -> None:
    recorder = _CleanupRecorder()
    app = create_app(runtime_factory=_fake_runtime_factory(recorder), settings=Settings())
    paths = {route.path for route in app.routes if hasattr(route, "path")}
    assert "/v1/chat/stream" in paths


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


def test_no_shared_budget_guard_in_lifespan_or_runtime() -> None:
    """Per-request budgets are owned by the ``/v1/chat/stream`` handler,
    never by the FastAPI lifespan or the runtime factory.

    Phase 15 added exactly one ``BudgetGuard(...)`` construction inside
    the route handler. That construction lives after the ``ready``
    gate and *before* ``register_request`` — so each request gets its
    own guard and the registry never binds one guard to two requests.

    ``runtime.py`` still has zero ``BudgetGuard`` constructions.
    """
    import re
    from pathlib import Path

    # runtime.py: no BudgetGuard construction anywhere.
    runtime_src = Path("src/expense_agent_svc/runtime.py").read_text()
    assert not re.search(r"\bBudgetGuard\s*\(", runtime_src), (
        "runtime.py constructs a BudgetGuard; per-request budgets belong to the route handler"
    )

    # app.py: exactly one construction, and it must sit inside the
    # chat_stream route handler (identified by 'async def chat_stream').
    app_src = Path("src/expense_agent_svc/app.py").read_text()
    hits = list(re.finditer(r"\bBudgetGuard\s*\(", app_src))
    assert len(hits) == 1, (
        f"app.py has {len(hits)} BudgetGuard constructions; expected exactly 1 "
        "(per-request, inside the chat_stream route)"
    )
    handler_start = app_src.index("async def chat_stream")
    lifespan_start = app_src.index("async def lifespan")
    lifespan_end = app_src.index("app = FastAPI(", lifespan_start)
    hit_idx = hits[0].start()
    assert hit_idx > handler_start, "BudgetGuard construction is not inside chat_stream"
    assert not (lifespan_start <= hit_idx <= lifespan_end), (
        "BudgetGuard construction leaked into the FastAPI lifespan"
    )


# ---------- POST /v1/chat/stream integration ----------


def _post_stream(client: TestClient, payload: dict[str, object]) -> Any:
    return client.post("/v1/chat/stream", json=payload)


def test_chat_stream_returns_ai_sdk_headers_and_final_frame() -> None:
    recorder = _CleanupRecorder()
    graph = _FakeCompiledGraph()
    app = create_app(
        runtime_factory=_fake_runtime_factory(recorder, graph=graph),
        settings=Settings(),
    )
    with TestClient(app) as client:
        response = _post_stream(
            client,
            {"question": "What is the deduction policy?", "tenant_id": "tenant-a"},
        )
        body = response.content
    assert response.status_code == 200
    assert "text/plain" in response.headers["content-type"]
    assert response.headers.get("x-vercel-ai-data-stream") == "v1"
    assert response.headers.get("cache-control") == "no-cache"
    assert response.headers.get("x-thread-id"), "X-Thread-Id must be echoed"
    assert response.headers.get("x-request-id"), "X-Request-Id must be echoed"
    # Body: at least one channel-0 fallback + one channel-2.
    lines = [line for line in body.split(b"\n") if line]
    channels = [line.split(b":", 1)[0].decode() for line in lines]
    assert "2" in channels, f"expected channel 2 in {channels!r}"


def test_chat_stream_supplied_thread_id_preserved() -> None:
    recorder = _CleanupRecorder()
    graph = _FakeCompiledGraph()
    app = create_app(
        runtime_factory=_fake_runtime_factory(recorder, graph=graph),
        settings=Settings(),
    )
    with TestClient(app) as client:
        response = _post_stream(
            client,
            {
                "question": "policy?",
                "tenant_id": "tenant-a",
                "thread_id": "client-thread-1",
            },
        )
    assert response.status_code == 200
    assert response.headers["x-thread-id"] == "client-thread-1"


def test_chat_stream_generates_thread_id_when_absent() -> None:
    recorder = _CleanupRecorder()
    graph = _FakeCompiledGraph()
    app = create_app(
        runtime_factory=_fake_runtime_factory(recorder, graph=graph),
        settings=Settings(),
    )
    with TestClient(app) as client:
        response = _post_stream(client, {"question": "policy?", "tenant_id": "tenant-a"})
    assert response.status_code == 200
    thread_id = response.headers["x-thread-id"]
    assert thread_id.startswith("thread-")
    assert len(thread_id) > len("thread-")


def test_chat_stream_rejects_unknown_field() -> None:
    recorder = _CleanupRecorder()
    graph = _FakeCompiledGraph()
    app = create_app(
        runtime_factory=_fake_runtime_factory(recorder, graph=graph),
        settings=Settings(),
    )
    with TestClient(app) as client:
        response = _post_stream(
            client,
            {"question": "policy?", "tenant_id": "tenant-a", "extra": "bad"},
        )
    assert response.status_code == 422


def test_chat_stream_rejects_invalid_tenant() -> None:
    recorder = _CleanupRecorder()
    graph = _FakeCompiledGraph()
    app = create_app(
        runtime_factory=_fake_runtime_factory(recorder, graph=graph),
        settings=Settings(),
    )
    with TestClient(app) as client:
        response = _post_stream(
            client,
            {"question": "policy?", "tenant_id": "tenant-zzz"},
        )
    assert response.status_code == 422


def test_chat_stream_returns_503_when_not_ready() -> None:
    recorder = _CleanupRecorder()
    graph = _FakeCompiledGraph()
    app = create_app(
        runtime_factory=_fake_runtime_factory(recorder, graph=graph),
        settings=Settings(),
    )
    # Do not enter TestClient — the lifespan never runs so app.state.ready is False.
    client = TestClient(app, raise_server_exceptions=False)
    response = client.post(
        "/v1/chat/stream",
        json={"question": "policy?", "tenant_id": "tenant-a"},
    )
    assert response.status_code == 503
    assert response.headers.get("retry-after") == "5"


def test_chat_stream_graph_receives_invocation_config_and_state() -> None:
    recorder = _CleanupRecorder()
    graph = _FakeCompiledGraph()
    app = create_app(
        runtime_factory=_fake_runtime_factory(recorder, graph=graph),
        settings=Settings(),
    )
    with TestClient(app) as client:
        _post_stream(
            client,
            {
                "question": "policy?",
                "tenant_id": "tenant-a",
                "thread_id": "custom-thread",
            },
        )
    cfg = graph.received_config
    assert isinstance(cfg, dict)
    assert cfg["recursion_limit"] == 25
    configurable = cfg["configurable"]
    assert isinstance(configurable, dict)
    assert configurable["thread_id"] == "custom-thread"
    seen_state = graph.received_input
    assert isinstance(seen_state, dict)
    assert seen_state["request_id"], "state must carry a request_id"
    assert seen_state["tenant_id"] == "tenant-a"
    assert seen_state["thread_id"] == "custom-thread"
    # Nothing non-serializable landed on the state.
    for value in seen_state.values():
        assert not callable(value)


def test_chat_stream_releases_registry_on_success() -> None:
    from expense_agent_svc.dependencies import _registry_size_for_tests

    recorder = _CleanupRecorder()
    graph = _FakeCompiledGraph()
    app = create_app(
        runtime_factory=_fake_runtime_factory(recorder, graph=graph),
        settings=Settings(),
    )
    starting = _registry_size_for_tests()
    with TestClient(app) as client:
        _post_stream(client, {"question": "policy?", "tenant_id": "tenant-a"})
    assert _registry_size_for_tests() == starting, (
        "chat_stream must release its RequestContext on success"
    )


def test_chat_stream_releases_registry_when_graph_raises() -> None:
    from expense_agent_svc.dependencies import _registry_size_for_tests

    recorder = _CleanupRecorder()

    class _RaisingGraph(_FakeCompiledGraph):
        def astream_events(
            self,
            input_state: object,
            config: object,
            *,
            version: str,
        ) -> AsyncIterator[dict[str, Any]]:
            del input_state, config
            assert version == "v2"

            async def _gen() -> AsyncIterator[dict[str, Any]]:
                if False:
                    yield {}
                raise RuntimeError("simulated failure")

            return _gen()

    graph = _RaisingGraph()
    app = create_app(
        runtime_factory=_fake_runtime_factory(recorder, graph=cast(Any, graph)),
        settings=Settings(),
    )
    starting = _registry_size_for_tests()
    with TestClient(app) as client:
        response = _post_stream(client, {"question": "policy?", "tenant_id": "tenant-a"})
    # The route returned 200 — the error was mapped to a channel-3 frame.
    assert response.status_code == 200
    assert b"internal_error" in response.content
    # And critically the registry entry was released.
    assert _registry_size_for_tests() == starting


def test_concurrent_requests_get_isolated_budget_guards() -> None:
    """Two concurrent chat requests must not share a BudgetGuard.

    We drive two logical requests through the same app with distinct
    tenant IDs and prove that each request produced a distinct
    ``RequestContext.budget`` via the debug hook.
    """
    from expense_agent_svc.dependencies import _registry_size_for_tests

    seen_budgets: list[int] = []

    class _RecordingGraph(_FakeCompiledGraph):
        def astream_events(
            self,
            input_state: object,
            config: object,
            *,
            version: str,
        ) -> AsyncIterator[dict[str, Any]]:
            self.received_input = cast(dict[str, object], input_state)
            self.received_config = cast(dict[str, object], config)
            assert version == "v2"
            # Read the caller's budget through the registry — proves
            # per-request context is registered before the graph runs.
            from expense_agent_svc.dependencies import get_request_context

            request_id = self.received_input["request_id"]
            assert isinstance(request_id, str)
            ctx = get_request_context(request_id)
            seen_budgets.append(id(ctx.budget))
            events = list(self.events)

            async def _gen() -> AsyncIterator[dict[str, Any]]:
                for ev in events:
                    yield ev

            return _gen()

    recorder = _CleanupRecorder()
    graph = _RecordingGraph()
    app = create_app(
        runtime_factory=_fake_runtime_factory(recorder, graph=cast(Any, graph)),
        settings=Settings(),
    )
    starting = _registry_size_for_tests()
    with TestClient(app) as client:
        _post_stream(client, {"question": "q1", "tenant_id": "tenant-a"})
        _post_stream(client, {"question": "q2", "tenant_id": "tenant-b"})
    assert len(seen_budgets) == 2
    assert seen_budgets[0] != seen_budgets[1], (
        "each request must own its BudgetGuard (id(budget) must differ)"
    )
    assert _registry_size_for_tests() == starting
