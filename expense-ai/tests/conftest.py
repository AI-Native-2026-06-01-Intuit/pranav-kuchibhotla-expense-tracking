"""Shared pytest fixtures."""

from __future__ import annotations

import os
from pathlib import Path

import pytest


def _is_ci() -> bool:
    return os.environ.get("CI") == "true" or os.environ.get("GITHUB_ACTIONS") == "true"


if not _is_ci():
    # Local-only workaround: Testcontainers Ryuk reaper listens on 8080 and
    # racks up conflicts on developer machines that already bind :8080
    # (e.g. a local k3d/Rancher proxy). Skipping the reaper is safe for
    # short-lived test containers: they still stop on context exit, and
    # stray containers can be removed with `docker container prune`.
    # CI should use Testcontainers' normal reaper behavior.
    os.environ.setdefault("TESTCONTAINERS_RYUK_DISABLED", "true")


@pytest.fixture(scope="session")
def fixtures_dir() -> Path:
    return Path(__file__).parent / "fixtures"


@pytest.fixture(scope="session")
def merchant_json_bytes(fixtures_dir: Path) -> bytes:
    return (fixtures_dir / "merchant_java.json").read_bytes()
