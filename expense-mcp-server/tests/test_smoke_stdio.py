"""stdio subprocess smoke test.

Spawns ``expense-mcp-server`` in a subprocess and drives it through the
official MCP Python client transport. Verifies:

* the four tools appear in ``tools/list``,
* the ``expense://catalogue`` resource appears in ``resources/list``,
* no stray stdout text corrupts the JSON-RPC framing,
* logs on stderr do not interfere with the protocol,
* a 100-frame stress loop of list_tools stays clean.

Upstream Spring endpoints are not required — we only exercise
``list_tools`` and ``list_resources`` which do not touch the network.
The actual tool bodies are covered by respx unit tests elsewhere.
"""

import sys

import pytest
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client


@pytest.mark.asyncio
async def test_stdio_lists_tools_and_resources() -> None:
    params = StdioServerParameters(
        command=sys.executable,
        args=["-m", "expense_mcp_server.transports.stdio"],
        # No real bearer needed: list_tools/list_resources don't call upstream.
        env={"EXPENSE_MCP_BEARER_JWT": "test-not-a-real-token"},
    )
    async with stdio_client(params) as (read, write), ClientSession(read, write) as session:
        await session.initialize()

        tools = await session.list_tools()
        names = {t.name for t in tools.tools}
        assert {
            "orders.get_order",
            "orders.create_refund",
            "llm.chat",
            "rag.retrieve_and_generate",
        }.issubset(names)

        resources = await session.list_resources()
        uris = {str(r.uri) for r in resources.resources}
        assert "expense://catalogue" in uris

        # 100-frame stress loop: repeat list_tools 100 times and
        # confirm every response is parseable JSON-RPC.
        for _ in range(100):
            again = await session.list_tools()
            assert again.tools
