"""Replay-script driver test."""

import json
from pathlib import Path

from expense_mcp_server.scripts.replay import run_replay


def test_replay_processes_all_four_tools() -> None:
    fixtures = Path(__file__).parent / "fixtures"
    summary = run_replay(fixtures)
    assert not summary["any_error"], summary["per_tool"]
    per_tool = summary["per_tool"]
    for tool in (
        "orders.get_order",
        "orders.create_refund",
        "llm.chat",
        "rag.retrieve_and_generate",
    ):
        stats = per_tool[tool]
        assert stats["count"] >= 1, f"{tool} had no fixtures"
        assert stats["errors"] == 0, f"{tool} errors: {stats['error_messages']}"


def test_replay_summary_json_shape() -> None:
    fixtures = Path(__file__).parent / "fixtures"
    summary = run_replay(fixtures)
    # Round-trip through json to catch non-serializable values.
    dumped = json.dumps(summary, sort_keys=True)
    reloaded = json.loads(dumped)
    assert set(reloaded["per_tool"].keys()) == {
        "orders.get_order",
        "orders.create_refund",
        "llm.chat",
        "rag.retrieve_and_generate",
    }
