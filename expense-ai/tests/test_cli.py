"""CLI tests."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from expense_ai.cli import main


def _valid_payload() -> dict[str, object]:
    return {
        "correlationId": "corr-abc",
        "merchant": {
            "id": "merchant-001",
            "tenantId": "tenant-synth",
            "name": "Acme",
            "category": "office_supplies",
            "amount": "12.34",
            "createdAt": "2026-01-15T12:00:00Z",
        },
        "modelId": "model-x",
    }


def test_cli_valid_input_prints_alias_json(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    path = tmp_path / "req.json"
    path.write_text(json.dumps(_valid_payload()))

    rc = main([str(path)])
    assert rc == 0

    captured = capsys.readouterr()
    parsed = json.loads(captured.out)
    assert parsed["correlationId"] == "corr-abc"
    assert parsed["merchant"]["tenantId"] == "tenant-synth"


def test_cli_invalid_json_returns_nonzero(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    path = tmp_path / "bad.json"
    path.write_text("{ not valid json")

    rc = main([str(path)])
    assert rc != 0
    captured = capsys.readouterr()
    assert "error" in captured.err.lower()


def test_cli_missing_path_returns_nonzero(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    path = tmp_path / "does-not-exist.json"
    rc = main([str(path)])
    assert rc != 0
    captured = capsys.readouterr()
    assert "not found" in captured.err.lower()


def test_cli_missing_argument_returns_nonzero(
    capsys: pytest.CaptureFixture[str],
) -> None:
    rc = main([])
    assert rc != 0
    captured = capsys.readouterr()
    assert "usage" in captured.err.lower()


def test_cli_validation_error_returns_nonzero(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    payload = _valid_payload()
    payload["correlationId"] = "nope-not-corr"
    path = tmp_path / "bad-req.json"
    path.write_text(json.dumps(payload))

    rc = main([str(path)])
    assert rc == 1
    captured = capsys.readouterr()
    assert "invalid" in captured.err.lower()
