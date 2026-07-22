"""expense://catalogue resource: registration + content shape."""

import json

from expense_mcp_server.app import mcp
from expense_mcp_server.transports import _registry  # noqa: F401


async def test_catalogue_is_registered() -> None:
    resources = await mcp.list_resources()
    uris = [str(r.uri) for r in resources]
    assert "expense://catalogue" in uris


async def test_catalogue_content_shape() -> None:
    result = await mcp.read_resource("expense://catalogue")
    # FastMCP returns an iterable of ReadResourceContents.
    contents = list(result)
    assert contents
    payload = json.loads(contents[0].content)
    assert payload["server"]["name"] == "expense-mcp-server"
    tool_names = {t["name"] for t in payload["tools"]}
    assert tool_names == {
        "orders.get_order",
        "orders.create_refund",
        "llm.chat",
        "rag.retrieve_and_generate",
    }
    assert "tenant-a" in payload["supported_tenants"]
    assert "corpus_stats" in payload
