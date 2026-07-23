# expense-agent-svc

W7D5 multi-agent orchestration service for the UptimeCrew expense platform.

## Status (Phase 0-5 scaffold)

This tree currently contains the service scaffold, settings surface, typed
serializable graph state with explicit reducers, and the runtime dependency /
per-request context architecture. Later phases add the budget guard, deadline
decorator, three LangGraph nodes (retrieval / API / synthesis), the supervisor
graph, the PostgresSaver checkpointer wiring, the SSE bridge for the
`expense-web` `useChat` client, trajectory evaluation, RAGAS production
sampling, deployment artifacts (Docker, Argo Application, CloudFormation
Budgets), CI, runbook, and the 30/60/90 plan.

## Package layout

    src/expense_agent_svc/
      __init__.py
      settings.py         # pydantic-settings, EXPENSE_AGENT_ prefix, SecretStr
      state.py            # TypedDict AgentState + explicit reducers
      dependencies.py     # runtime deps + per-request context registry
    tests/
      test_settings.py
      test_state_reducers.py
      test_dependencies.py

Non-serializable objects (MCP sessions, Anthropic clients, Postgres pools,
`BudgetGuard`) live in `dependencies.py` and never enter `AgentState`. Only
serializable graph state is checkpointed by `PostgresSaver`.

## Local development

    cd expense-agent-svc
    uv sync
    uv run ruff check
    uv run ruff format --check
    uv run mypy --strict src/ tests/
    uv run pytest -q
