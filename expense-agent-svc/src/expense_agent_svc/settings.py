"""Typed settings surface for expense-agent-svc.

All configuration is loaded from environment variables prefixed with
``EXPENSE_AGENT_`` (via ``pydantic-settings``). Secrets are wrapped in
:class:`pydantic.SecretStr` so their values never appear in ``repr``,
``str``, or default logging.

Nothing in this module reads a secret or instantiates a network client
at import time. The ``Settings`` object is only constructed when a
caller (test, FastAPI lifespan, CLI) explicitly calls
:func:`get_settings`. This matches the sibling ``expense-mcp-server``
pattern and keeps unit tests hermetic.
"""

from __future__ import annotations

from pydantic import Field, SecretStr, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Runtime configuration for the agent service."""

    model_config = SettingsConfigDict(
        env_prefix="EXPENSE_AGENT_",
        env_file=None,
        # Reject unknown env vars so a typo in EXPENSE_AGENT_MODEL_NAM never
        # silently falls back to the default in production.
        extra="ignore",
        frozen=True,
        case_sensitive=False,
    )

    # --- Postgres (LangGraph PostgresSaver checkpoint store) ---
    postgres_url: str = Field(
        default="postgresql://postgres:postgres@localhost:5432/postgres",
        description="Postgres connection string for the durable checkpointer.",
    )

    # --- MCP transport (published by expense-mcp-server SSE) ---
    mcp_sse_url: str = Field(
        default="http://127.0.0.1:8080/sse",
        description="SSE URL of the expense-mcp-server transport.",
    )
    mcp_bearer_jwt: SecretStr = Field(
        default=SecretStr(""),
        description="Signed bearer JWT presented to the MCP SSE middleware.",
    )

    # --- LLM + tracing credentials ---
    anthropic_api_key: SecretStr = Field(
        default=SecretStr(""),
        description="Anthropic API key; empty string means unset (unit tests).",
    )
    langsmith_api_key: SecretStr | None = Field(
        default=None,
        description="LangSmith API key. Optional; RAGAS sampling and root "
        "traces still work locally when unset.",
    )
    langsmith_project: str = Field(default="expense-agent-svc-dev")

    # --- Model + retrieval configuration ---
    model_name: str = Field(default="claude-sonnet-4-5")
    reranker: str = Field(default="bge-reranker-base")

    # --- Guardrails ---
    # RAGAS sampling: fraction of grounded answers evaluated in prod. Kept
    # low so a spike in traffic does not multiply LLM cost.
    ragas_sample_rate: float = Field(default=0.01, ge=0.0, le=1.0)
    # Integer cost is the source of truth (see budgets.py). Unit is 1e-5 USD.
    request_budget_usd_e5: int = Field(default=25_000, ge=0)
    recursion_limit: int = Field(default=25, ge=1)
    retrieval_deadline_s: float = Field(default=3.0, gt=0.0)
    api_deadline_s: float = Field(default=5.0, gt=0.0)
    synthesis_deadline_s: float = Field(default=8.0, gt=0.0)

    # --- HTTP surface ---
    host: str = Field(default="0.0.0.0")
    port: int = Field(default=8080, ge=1, le=65535)
    environment: str = Field(default="dev")

    # --- Local / CI ergonomics ---
    allow_external_eval_skip: bool = Field(default=False)

    @field_validator("postgres_url")
    @classmethod
    def _validate_postgres_url(cls, v: str) -> str:
        if not v.startswith(("postgresql://", "postgres://")):
            raise ValueError("postgres_url must start with postgresql:// or postgres://")
        return v

    @field_validator("mcp_sse_url")
    @classmethod
    def _validate_mcp_url(cls, v: str) -> str:
        if not v.startswith(("http://", "https://")):
            raise ValueError("mcp_sse_url must be an http(s) URL")
        return v


def get_settings() -> Settings:
    """Return a fresh :class:`Settings` snapshot from the current environment.

    Callers should treat the returned object as read-only. A fresh snapshot
    is returned rather than a cached module global so that tests can
    monkeypatch ``os.environ`` between cases without spillover.
    """
    return Settings()
