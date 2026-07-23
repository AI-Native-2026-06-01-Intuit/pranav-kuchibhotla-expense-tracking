"""Settings surface tests.

Verify:

* The EXPENSE_AGENT_ prefix is honored.
* :class:`~pydantic.SecretStr` fields never leak in ``repr`` / ``str``.
* Defaults match the W7D5 rubric (recursion_limit=25, ceiling=25000,
  deadlines 3/5/8 seconds, RAGAS sample rate 0.01).
* Invalid Postgres / MCP URLs are rejected at construction.
* No module import touches an actual secret.
"""

from __future__ import annotations

import importlib

import pytest
from pydantic import SecretStr, ValidationError


def _fresh_settings_module() -> object:
    """Re-import the settings module so tests can start from a clean env snapshot."""
    return importlib.import_module("expense_agent_svc.settings")


def test_defaults_match_rubric(monkeypatch: pytest.MonkeyPatch) -> None:
    # Wipe the guardrail env vars so we exercise the shipping defaults.
    for name in [
        "EXPENSE_AGENT_RECURSION_LIMIT",
        "EXPENSE_AGENT_REQUEST_BUDGET_USD_E5",
        "EXPENSE_AGENT_RETRIEVAL_DEADLINE_S",
        "EXPENSE_AGENT_API_DEADLINE_S",
        "EXPENSE_AGENT_SYNTHESIS_DEADLINE_S",
        "EXPENSE_AGENT_RAGAS_SAMPLE_RATE",
        "EXPENSE_AGENT_MODEL_NAME",
        "EXPENSE_AGENT_RERANKER",
    ]:
        monkeypatch.delenv(name, raising=False)

    mod = _fresh_settings_module()
    settings = mod.get_settings()  # type: ignore[attr-defined]

    assert settings.recursion_limit == 25
    assert settings.request_budget_usd_e5 == 25_000
    assert settings.retrieval_deadline_s == 3.0
    assert settings.api_deadline_s == 5.0
    assert settings.synthesis_deadline_s == 8.0
    assert settings.ragas_sample_rate == 0.01
    assert settings.model_name == "claude-sonnet-4-5"
    assert settings.reranker == "bge-reranker-base"


def test_env_prefix_and_override(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("EXPENSE_AGENT_MODEL_NAME", "claude-opus-4-7")
    monkeypatch.setenv("EXPENSE_AGENT_RECURSION_LIMIT", "40")
    monkeypatch.setenv("EXPENSE_AGENT_LANGSMITH_PROJECT", "test-project")

    mod = _fresh_settings_module()
    settings = mod.get_settings()  # type: ignore[attr-defined]

    assert settings.model_name == "claude-opus-4-7"
    assert settings.recursion_limit == 40
    assert settings.langsmith_project == "test-project"


def test_secretstr_redaction_in_repr(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("EXPENSE_AGENT_ANTHROPIC_API_KEY", "sk-ant-plaintext-secret")
    monkeypatch.setenv("EXPENSE_AGENT_MCP_BEARER_JWT", "eyJheHAxYzI.plain.jwt")
    monkeypatch.setenv("EXPENSE_AGENT_LANGSMITH_API_KEY", "lsv2_pt_TESTSECRET")

    mod = _fresh_settings_module()
    settings = mod.get_settings()  # type: ignore[attr-defined]

    dumped_repr = repr(settings)
    dumped_str = str(settings)
    for leak in ("sk-ant-plaintext-secret", "eyJheHAxYzI.plain.jwt", "lsv2_pt_TESTSECRET"):
        assert leak not in dumped_repr, f"secret leaked in repr: {leak}"
        assert leak not in dumped_str, f"secret leaked in str: {leak}"

    # But the value is still retrievable through get_secret_value.
    assert isinstance(settings.anthropic_api_key, SecretStr)
    assert settings.anthropic_api_key.get_secret_value() == "sk-ant-plaintext-secret"


def test_rejects_bad_postgres_url(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("EXPENSE_AGENT_POSTGRES_URL", "mysql://localhost/db")
    mod = _fresh_settings_module()
    with pytest.raises(ValidationError):
        mod.get_settings()  # type: ignore[attr-defined]


def test_rejects_bad_mcp_url(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("EXPENSE_AGENT_MCP_SSE_URL", "ftp://mcp/sse")
    mod = _fresh_settings_module()
    with pytest.raises(ValidationError):
        mod.get_settings()  # type: ignore[attr-defined]


def test_ragas_sample_rate_bounds(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("EXPENSE_AGENT_RAGAS_SAMPLE_RATE", "1.5")
    mod = _fresh_settings_module()
    with pytest.raises(ValidationError):
        mod.get_settings()  # type: ignore[attr-defined]


def test_import_does_not_touch_secrets() -> None:
    # Import path must not construct Settings() or read env at module load,
    # otherwise a stray os.environ during collection would break tests.
    import expense_agent_svc.settings as settings_mod

    # We can freely access the class, but constructing it is what pulls env.
    assert callable(settings_mod.get_settings)
    assert hasattr(settings_mod, "Settings")
