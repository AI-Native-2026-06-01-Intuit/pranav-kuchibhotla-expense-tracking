"""respx tests for the llm.chat tool: bearer forwarding, 429 mapping, shaping."""

import httpx
import pytest
import respx
from mcp import McpError

from expense_mcp_server.errors import CODE_TOO_MANY_REQUESTS
from expense_mcp_server.tools.llm import _chat_impl
from expense_mcp_server.tools.schemas import ChatArgs, ChatMessage


@pytest.fixture
def bearer() -> str:
    return "test-bearer-not-a-real-token"


@respx.mock
async def test_chat_success_pre_shapes_response(bearer: str) -> None:
    respx.post("https://llm.test/api/v1/llm/chat").mock(
        return_value=httpx.Response(
            200,
            json={
                "text": "hi",
                "model": "claude-sonnet-4-5",
                "usage_input_tokens": 5,
                "usage_output_tokens": 3,
                "cost_usd_minor": 2,
                # Extra key that must be dropped:
                "internal_debug": "leaked?",
            },
        )
    )
    client = httpx.AsyncClient(base_url="https://llm.test")
    answer = await _chat_impl(
        client,
        ChatArgs(
            messages=[ChatMessage(role="user", content="hello")],
            max_tokens=32,
            tenant_id="tenant-a",
        ),
        bearer,
    )
    await client.aclose()
    assert answer.text == "hi"
    assert answer.model == "claude-sonnet-4-5"
    assert answer.usage_input_tokens == 5
    # The ChatAnswer schema forbids extras, so any leaked key is dropped.
    assert not hasattr(answer, "internal_debug")


@respx.mock
async def test_chat_forwards_bearer(bearer: str) -> None:
    route = respx.post("https://llm.test/api/v1/llm/chat").mock(
        return_value=httpx.Response(200, json={"text": "hi", "model": "m"})
    )
    client = httpx.AsyncClient(base_url="https://llm.test")
    await _chat_impl(
        client,
        ChatArgs(
            messages=[ChatMessage(role="user", content="hi")],
            max_tokens=8,
            tenant_id="tenant-a",
        ),
        bearer,
    )
    await client.aclose()
    assert route.calls.last.request.headers["Authorization"] == f"Bearer {bearer}"


@respx.mock
async def test_chat_429_maps_to_4290(bearer: str) -> None:
    respx.post("https://llm.test/api/v1/llm/chat").mock(
        return_value=httpx.Response(429, text="slow down")
    )
    client = httpx.AsyncClient(base_url="https://llm.test")
    with pytest.raises(McpError) as excinfo:
        await _chat_impl(
            client,
            ChatArgs(
                messages=[ChatMessage(role="user", content="hi")],
                max_tokens=8,
                tenant_id="tenant-a",
            ),
            bearer,
        )
    await client.aclose()
    assert excinfo.value.error.code == CODE_TOO_MANY_REQUESTS
