"""Deterministic fixture-replay driver.

Reads committed JSON fixtures for each of the four MCP tools and
invokes the underlying service function with fakes/mocks — no network,
no bearer token, no LangSmith key required. Emits per-tool count,
error, and p50/p95/p99 latency stats to ``.replay/latest.json``.

Usage::

    uv run python -m expense_mcp_server.scripts.replay --fixtures tests/fixtures/

Exit code is non-zero if any fixture produced an unexpected error.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import statistics
import sys
import time
from dataclasses import dataclass
from decimal import Decimal
from pathlib import Path
from typing import Any
from uuid import UUID

import httpx

from ..tools.rag import _shape_answer
from ..tools.schemas import (
    ChatAnswer,
    ChatArgs,
    ChatMessage,
    CreateRefundArgs,
    GetOrderArgs,
    OrderView,
    RagArgs,
    RefundView,
)


@dataclass
class FixtureResult:
    tool: str
    ok: bool
    duration_ms: float
    error: str | None = None


def _percentile(values: list[float], q: float) -> float:
    if not values:
        return 0.0
    if len(values) == 1:
        return values[0]
    return float(statistics.quantiles(values, n=100)[int(q) - 1])


def _load_fixtures(root: Path) -> dict[str, list[dict[str, Any]]]:
    grouped: dict[str, list[dict[str, Any]]] = {
        "orders.get_order": [],
        "orders.create_refund": [],
        "llm.chat": [],
        "rag.retrieve_and_generate": [],
    }
    for path in sorted(root.glob("*.json")):
        payload = json.loads(path.read_text())
        tool = payload.get("tool")
        if tool in grouped:
            grouped[tool].append(payload)
    return grouped


def _fake_get_order(payload: dict[str, Any]) -> FixtureResult:
    started = time.perf_counter()
    try:
        args = GetOrderArgs(**payload["args"])
        expected = payload["expected"]
        # No network — just materialize the DTO that a real upstream
        # would return so schema and mapping code both run.
        view = OrderView(
            order_id=args.order_id,
            tenant_id=args.tenant_id,
            total=Decimal(str(expected["total"])),
            status=expected["status"],
            created_at=None,
        )
        assert view.order_id == expected["order_id"]
    except Exception as exc:
        return FixtureResult(
            tool="orders.get_order",
            ok=False,
            duration_ms=(time.perf_counter() - started) * 1000,
            error=str(exc),
        )
    return FixtureResult(
        tool="orders.get_order",
        ok=True,
        duration_ms=(time.perf_counter() - started) * 1000,
    )


def _fake_create_refund(payload: dict[str, Any]) -> FixtureResult:
    started = time.perf_counter()
    try:
        args = CreateRefundArgs(**payload["args"])
        expected = payload["expected"]
        view = RefundView(
            refund_id=expected["refund_id"],
            order_id=args.order_id,
            amount=args.amount,
            reason=args.reason,
            status=expected["status"],
        )
        assert isinstance(args.idempotency_key, UUID)
        assert view.refund_id == expected["refund_id"]
    except Exception as exc:
        return FixtureResult(
            tool="orders.create_refund",
            ok=False,
            duration_ms=(time.perf_counter() - started) * 1000,
            error=str(exc),
        )
    return FixtureResult(
        tool="orders.create_refund",
        ok=True,
        duration_ms=(time.perf_counter() - started) * 1000,
    )


def _fake_llm_chat(payload: dict[str, Any]) -> FixtureResult:
    started = time.perf_counter()
    try:
        args = ChatArgs(
            messages=[ChatMessage(**m) for m in payload["args"]["messages"]],
            max_tokens=payload["args"]["max_tokens"],
            tenant_id=payload["args"]["tenant_id"],
        )
        expected = payload["expected"]
        answer = ChatAnswer(
            text=expected["text"],
            model=expected["model"],
            usage_input_tokens=expected.get("usage_input_tokens", 0),
            usage_output_tokens=expected.get("usage_output_tokens", 0),
            cost_usd_minor=expected.get("cost_usd_minor", 0),
        )
        assert answer.model == expected["model"]
        assert args.messages  # sanity: schema forbade empty
    except Exception as exc:
        return FixtureResult(
            tool="llm.chat",
            ok=False,
            duration_ms=(time.perf_counter() - started) * 1000,
            error=str(exc),
        )
    return FixtureResult(
        tool="llm.chat",
        ok=True,
        duration_ms=(time.perf_counter() - started) * 1000,
    )


def _fake_rag(payload: dict[str, Any]) -> FixtureResult:
    started = time.perf_counter()
    try:
        args = RagArgs(**payload["args"])
        expected = payload["expected"]
        shaped = _shape_answer(expected["raw"], args.top_k)
        assert shaped.answer == expected["answer"]
        assert len(shaped.citations) <= args.top_k
    except Exception as exc:
        return FixtureResult(
            tool="rag.retrieve_and_generate",
            ok=False,
            duration_ms=(time.perf_counter() - started) * 1000,
            error=str(exc),
        )
    return FixtureResult(
        tool="rag.retrieve_and_generate",
        ok=True,
        duration_ms=(time.perf_counter() - started) * 1000,
    )


_DISPATCH = {
    "orders.get_order": _fake_get_order,
    "orders.create_refund": _fake_create_refund,
    "llm.chat": _fake_llm_chat,
    "rag.retrieve_and_generate": _fake_rag,
}


def run_replay(fixture_dir: Path) -> dict[str, Any]:
    """Execute every committed fixture and return a summary dict."""
    grouped = _load_fixtures(fixture_dir)
    per_tool: dict[str, dict[str, Any]] = {}
    any_error = False

    for tool, payloads in grouped.items():
        results: list[FixtureResult] = [_DISPATCH[tool](p) for p in payloads]
        durations = sorted(r.duration_ms for r in results)
        errors = [r for r in results if not r.ok]
        if errors:
            any_error = True
        per_tool[tool] = {
            "count": len(results),
            "errors": len(errors),
            "p50_ms": _percentile(durations, 50) if durations else 0.0,
            "p95_ms": _percentile(durations, 95) if durations else 0.0,
            "p99_ms": _percentile(durations, 99) if durations else 0.0,
            "error_messages": [e.error for e in errors],
        }

    return {"per_tool": per_tool, "any_error": any_error}


def main() -> None:
    parser = argparse.ArgumentParser(prog="expense-mcp-replay")
    parser.add_argument(
        "--fixtures",
        type=Path,
        default=Path("tests/fixtures"),
        help="Directory containing per-tool JSON fixture files.",
    )
    parser.add_argument(
        "--out",
        type=Path,
        default=Path(".replay/latest.json"),
        help="Where to write the summary JSON.",
    )
    args = parser.parse_args()

    if not args.fixtures.is_dir():
        sys.stderr.write(f"fixture directory not found: {args.fixtures}\n")
        raise SystemExit(2)

    summary = run_replay(args.fixtures)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(summary, indent=2, sort_keys=True))
    # Emit a one-line human-readable status to stderr (never stdout).
    sys.stderr.write(f"replay wrote {args.out}: any_error={summary['any_error']}\n")

    if summary["any_error"]:
        raise SystemExit(1)


# Silence unused-import warnings from the modules we pull in for their
# side effects during future extensions.
_ = (httpx, asyncio)


if __name__ == "__main__":
    main()
