"""Application settings loaded from environment / .env / secrets dir."""

from __future__ import annotations

from typing import Literal

from pydantic import Field, HttpUrl, SecretStr, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class ExpenseAiSettings(BaseSettings):  # type: ignore[explicit-any]
    """Runtime configuration for the sidecar.

    Secrets use SecretStr so that ``repr()`` and structured logging never
    leak the underlying value. Callers must go through
    ``proxy_api_key.get_secret_value()`` explicitly.
    """

    model_config = SettingsConfigDict(
        env_prefix="EXPENSE_AI_",
        env_file=".env",
        env_file_encoding="utf-8",
        secrets_dir="/run/secrets",
        extra="forbid",
        frozen=True,
    )

    proxy_base_url: HttpUrl
    proxy_api_key: SecretStr
    proxy_timeout_seconds: float = Field(default=30.0, ge=1.0, le=300.0)
    proxy_max_retries: int = Field(default=3, ge=1, le=10)
    model_id: str
    tenant_id: str
    log_level: Literal["DEBUG", "INFO", "WARNING", "ERROR"] = "INFO"

    # W7D2 additions — all optional so W7D1 callers/tests keep working.
    langsmith_api_key: SecretStr | None = None
    langsmith_project: str = "expense-ai-dev"
    pg_dsn: str | None = None
    anthropic_api_key: SecretStr | None = None

    @field_validator("tenant_id")
    @classmethod
    def _tenant_id_prefix(cls, value: str) -> str:
        if not value.startswith("tenant-"):
            raise ValueError("tenant_id must start with 'tenant-'")
        return value
