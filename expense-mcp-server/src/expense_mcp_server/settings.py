"""Runtime settings for the expense MCP server.

Loaded from environment variables prefixed with ``EXPENSE_MCP_`` and,
optionally, from a local ``.env`` file. The bearer JWT is wrapped in
``SecretStr`` so ``repr(settings)`` and structured log renderings do
not accidentally leak the token.
"""

from __future__ import annotations

from functools import lru_cache

from pydantic import Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Pydantic-settings model for the MCP server."""

    model_config = SettingsConfigDict(
        env_prefix="EXPENSE_MCP_",
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    orders_svc_url: str = Field(default="http://localhost:8080")
    llm_proxy_url: str = Field(default="http://localhost:8080")
    bearer_jwt: SecretStr = Field(default=SecretStr(""))

    langsmith_project: str = Field(default="expense-mcp-server")

    tool_timeout_default_s: float = Field(default=5.0, gt=0)
    tool_timeout_rag_s: float = Field(default=30.0, gt=0)

    host: str = Field(default="0.0.0.0")
    port: int = Field(default=8080, ge=1, le=65535)

    jwt_audience: str = Field(default="")
    jwks_url: str = Field(default="")
    jwt_issuer: str = Field(default="")
    # Refresh cadence for the JWKS document. A shorter window is safer but
    # noisier; 15 min matches common IdP key-rotation cadences.
    jwks_cache_ttl_s: float = Field(default=900.0, gt=0)

    postgres_dsn: str = Field(default="")
    redis_url: str = Field(default="")

    def has_jwt_validation(self) -> bool:
        """Whether the SSE transport is configured for cryptographic JWT verification.

        Both an audience and a JWKS URL must be configured. There is no
        presence-only fallback: :func:`transports.sse.build_app` raises at
        startup when this returns False, so an unverifiable token can never
        traverse the network transport.
        """
        return bool(self.jwt_audience) and bool(self.jwks_url)


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Return the process-wide settings singleton."""
    return Settings()
