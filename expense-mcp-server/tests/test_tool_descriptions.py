"""Description-quality gate.

Each tool description must:
    * be at least 200 characters,
    * include the routing phrases ``Use this`` and ``Do NOT`` (case-sensitive),
    * end with a concrete example.
"""

import pytest

from expense_mcp_server.app import mcp
from expense_mcp_server.transports import _registry  # noqa: F401 - registers tools


@pytest.mark.parametrize(
    "tool_name",
    [
        "orders.get_order",
        "orders.create_refund",
        "llm.chat",
        "rag.retrieve_and_generate",
    ],
)
async def test_tool_description_meets_quality_gate(tool_name: str) -> None:
    tools = await mcp.list_tools()
    match = next((t for t in tools if t.name == tool_name), None)
    assert match is not None, f"tool {tool_name} not registered"
    desc = match.description or ""
    assert len(desc) >= 200, f"description too short for {tool_name}: {len(desc)}"
    assert "Use this" in desc, f"{tool_name} description missing 'Use this'"
    assert "Do NOT" in desc, f"{tool_name} description missing 'Do NOT'"
    assert "Example" in desc or "example" in desc, f"{tool_name} lacks an example"
