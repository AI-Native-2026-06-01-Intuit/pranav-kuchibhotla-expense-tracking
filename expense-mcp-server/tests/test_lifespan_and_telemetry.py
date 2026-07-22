"""Lifespan + telemetry + replay-entrypoint coverage.

These aren't behavior tests — they exercise the wiring code that only
runs at process boundaries so a regression in startup, log config, or
the replay CLI cannot slip past unit gates.
"""

import io
import json
import sys
from pathlib import Path
from typing import Any

import pytest

from expense_mcp_server.app import Deps, deps_from, lifespan
from expense_mcp_server.scripts.replay import main as replay_main
from expense_mcp_server.settings import Settings
from expense_mcp_server.telemetry import configure_logging, get_logger


async def test_lifespan_opens_and_closes_clients() -> None:
    async with lifespan(None) as deps:  # type: ignore[arg-type]
        assert isinstance(deps, Deps)
        assert deps.orders_client is not None
        assert deps.llm_client is not None
        # rag_call is either the real function or the sentinel raiser;
        # either shape must be callable.
        assert callable(deps.rag_call)


def test_configure_logging_directs_output_to_stderr() -> None:
    # Route stderr through a StringIO so we can prove no log line lands
    # on stdout — which would corrupt stdio JSON-RPC framing.
    captured_stderr = io.StringIO()
    captured_stdout = io.StringIO()
    old_err, old_out = sys.stderr, sys.stdout
    try:
        sys.stderr = captured_stderr
        sys.stdout = captured_stdout
        configure_logging()
        get_logger("test").info("startup_probe", where="stderr")
    finally:
        sys.stderr = old_err
        sys.stdout = old_out
    # Explicitly assert stdout is untouched; the JSON payload landed on stderr.
    assert captured_stdout.getvalue() == ""
    assert "startup_probe" in captured_stderr.getvalue()


def test_deps_from_rejects_uninitialized_context() -> None:
    class FakeCtx:
        class request_context:
            lifespan_context = object()

    with pytest.raises(RuntimeError):
        deps_from(FakeCtx())  # type: ignore[arg-type]


def test_settings_hides_secret_repr(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("EXPENSE_MCP_BEARER_JWT", "should-not-appear-in-repr")
    s = Settings()
    # SecretStr renders as '**********' — the actual token must not leak.
    assert "should-not-appear-in-repr" not in repr(s)
    assert "should-not-appear-in-repr" not in str(s)
    # But the runtime accessor gets the real value.
    assert s.bearer_jwt.get_secret_value() == "should-not-appear-in-repr"


def test_settings_has_jwt_validation_gate() -> None:
    s = Settings()
    assert s.has_jwt_validation() is False
    s2 = Settings(jwt_audience="a", jwks_url="https://x")
    assert s2.has_jwt_validation() is True


def test_replay_cli_writes_output(tmp_path: Path) -> None:
    fixture_dir = Path(__file__).parent / "fixtures"
    out = tmp_path / "replay.json"
    old_argv = sys.argv
    try:
        sys.argv = [
            "expense-mcp-replay",
            "--fixtures",
            str(fixture_dir),
            "--out",
            str(out),
        ]
        replay_main()
    finally:
        sys.argv = old_argv
    payload: dict[str, Any] = json.loads(out.read_text())
    assert "per_tool" in payload
    assert payload["any_error"] is False


def test_replay_cli_missing_fixtures_exits_nonzero(tmp_path: Path) -> None:
    out = tmp_path / "replay.json"
    old_argv = sys.argv
    try:
        sys.argv = [
            "expense-mcp-replay",
            "--fixtures",
            str(tmp_path / "does-not-exist"),
            "--out",
            str(out),
        ]
        with pytest.raises(SystemExit) as excinfo:
            replay_main()
    finally:
        sys.argv = old_argv
    assert excinfo.value.code == 2
