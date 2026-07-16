"""Shared pytest fixtures."""

from __future__ import annotations

from pathlib import Path

import pytest


@pytest.fixture(scope="session")
def fixtures_dir() -> Path:
    return Path(__file__).parent / "fixtures"


@pytest.fixture(scope="session")
def merchant_json_bytes(fixtures_dir: Path) -> bytes:
    return (fixtures_dir / "merchant_java.json").read_bytes()
