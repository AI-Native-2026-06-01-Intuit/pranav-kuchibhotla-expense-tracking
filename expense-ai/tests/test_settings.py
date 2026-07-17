"""Tests for ExpenseAiSettings."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from expense_ai.settings import ExpenseAiSettings

SECRET_VALUE = "test-key-do-not-log"


def _set_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("EXPENSE_AI_PROXY_BASE_URL", "http://localhost:8080")
    monkeypatch.setenv("EXPENSE_AI_PROXY_API_KEY", SECRET_VALUE)
    monkeypatch.setenv("EXPENSE_AI_TENANT_ID", "tenant-synth")
    monkeypatch.setenv("EXPENSE_AI_MODEL_ID", "model-x")


def test_settings_load_from_env(monkeypatch: pytest.MonkeyPatch) -> None:
    _set_env(monkeypatch)
    settings = ExpenseAiSettings()
    assert settings.tenant_id == "tenant-synth"
    assert settings.model_id == "model-x"
    assert settings.proxy_timeout_seconds == 30.0
    assert settings.proxy_max_retries == 3


def test_settings_repr_hides_secret(monkeypatch: pytest.MonkeyPatch) -> None:
    _set_env(monkeypatch)
    settings = ExpenseAiSettings()
    text = repr(settings)
    assert SECRET_VALUE not in text
    assert "SecretStr" in text or "**" in text


def test_settings_secret_only_via_get_secret_value(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _set_env(monkeypatch)
    settings = ExpenseAiSettings()
    assert settings.proxy_api_key.get_secret_value() == SECRET_VALUE


def test_settings_invalid_tenant_id_fails(monkeypatch: pytest.MonkeyPatch) -> None:
    _set_env(monkeypatch)
    monkeypatch.setenv("EXPENSE_AI_TENANT_ID", "acct-1")
    with pytest.raises(ValidationError):
        ExpenseAiSettings()


def test_settings_w7d2_optional_fields_default(monkeypatch: pytest.MonkeyPatch) -> None:
    _set_env(monkeypatch)
    settings = ExpenseAiSettings()
    assert settings.langsmith_api_key is None
    assert settings.langsmith_project == "expense-ai-dev"
    assert settings.pg_dsn is None
    assert settings.anthropic_api_key is None


def test_settings_w7d2_secrets_hide_in_repr(monkeypatch: pytest.MonkeyPatch) -> None:
    _set_env(monkeypatch)
    monkeypatch.setenv("EXPENSE_AI_LANGSMITH_API_KEY", "langsmith-do-not-log")
    monkeypatch.setenv("EXPENSE_AI_ANTHROPIC_API_KEY", "anthropic-do-not-log")
    settings = ExpenseAiSettings()
    text = repr(settings)
    assert "langsmith-do-not-log" not in text
    assert "anthropic-do-not-log" not in text
    assert settings.langsmith_api_key is not None
    assert settings.langsmith_api_key.get_secret_value() == "langsmith-do-not-log"
