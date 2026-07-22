"""respx-driven tests for orders.get_order and orders.create_refund."""

from decimal import Decimal
from uuid import UUID, uuid4

import httpx
import pytest
import respx
from mcp import McpError

from expense_mcp_server.errors import (
    CODE_CONFLICT,
    CODE_FORBIDDEN,
    CODE_NOT_FOUND,
    CODE_TOO_MANY_REQUESTS,
)
from expense_mcp_server.tools.orders import _create_refund_impl, _get_order_impl
from expense_mcp_server.tools.schemas import CreateRefundArgs, GetOrderArgs


def _v4() -> UUID:
    return uuid4()


@pytest.fixture
def bearer() -> str:
    return "test-bearer-not-a-real-token"


async def _client() -> httpx.AsyncClient:
    return httpx.AsyncClient(base_url="https://spring.test")


@respx.mock
async def test_get_order_success_forwards_bearer_and_tenant(bearer: str) -> None:
    route = respx.get("https://spring.test/api/v1/orders/ord-9001").mock(
        return_value=httpx.Response(
            200,
            json={
                "orderId": "ord-9001",
                "tenantId": "tenant-a",
                "total": "129.99",
                "status": "OPEN",
                "createdAt": "2026-07-20T10:00:00Z",
            },
        )
    )
    client = httpx.AsyncClient(base_url="https://spring.test")
    view = await _get_order_impl(
        client,
        GetOrderArgs(order_id="ord-9001", tenant_id="tenant-a"),
        bearer,
    )
    await client.aclose()

    assert view.order_id == "ord-9001"
    assert view.total == Decimal("129.99")
    request = route.calls.last.request
    assert request.headers["Authorization"] == f"Bearer {bearer}"
    assert request.headers["X-Tenant-Id"] == "tenant-a"


@respx.mock
async def test_get_order_404_maps_to_4040(bearer: str) -> None:
    respx.get("https://spring.test/api/v1/orders/missing").mock(
        return_value=httpx.Response(404, text="not found")
    )
    client = httpx.AsyncClient(base_url="https://spring.test")
    with pytest.raises(McpError) as excinfo:
        await _get_order_impl(
            client,
            GetOrderArgs(order_id="missing", tenant_id="tenant-a"),
            bearer,
        )
    await client.aclose()
    assert excinfo.value.error.code == CODE_NOT_FOUND


@respx.mock
async def test_create_refund_sends_amount_as_string_and_uuid_header(bearer: str) -> None:
    key = _v4()
    route = respx.post("https://spring.test/api/v1/orders/ord-9001/refunds").mock(
        return_value=httpx.Response(
            200,
            json={
                "refundId": "ref-abc",
                "orderId": "ord-9001",
                "amount": "10.00",
                "reason": "duplicate charge",
                "status": "SETTLED",
            },
        )
    )
    client = httpx.AsyncClient(base_url="https://spring.test")
    view = await _create_refund_impl(
        client,
        CreateRefundArgs(
            order_id="ord-9001",
            amount=Decimal("10.00"),
            reason="duplicate charge",
            tenant_id="tenant-a",
            idempotency_key=key,
        ),
        bearer,
    )
    await client.aclose()

    assert view.refund_id == "ref-abc"
    request = route.calls.last.request
    body = request.content.decode()
    # Amount travels as a JSON string, never float.
    assert '"amount": "10.00"' in body or '"amount":"10.00"' in body
    # Idempotency key echoes into both body and header.
    assert str(key) in body
    assert request.headers["Idempotency-Key"] == str(key)
    assert request.headers["Authorization"] == f"Bearer {bearer}"


@respx.mock
async def test_create_refund_same_key_same_upstream_call(bearer: str) -> None:
    key = _v4()
    route = respx.post("https://spring.test/api/v1/orders/ord-9001/refunds").mock(
        return_value=httpx.Response(
            200,
            json={
                "refundId": "ref-idem-1",
                "orderId": "ord-9001",
                "amount": "5.00",
                "reason": "duplicate",
                "status": "SETTLED",
            },
        )
    )
    client = httpx.AsyncClient(base_url="https://spring.test")
    args = CreateRefundArgs(
        order_id="ord-9001",
        amount=Decimal("5.00"),
        reason="duplicate charge",
        tenant_id="tenant-a",
        idempotency_key=key,
    )
    v1 = await _create_refund_impl(client, args, bearer)
    v2 = await _create_refund_impl(client, args, bearer)
    await client.aclose()

    # Two calls with the same key see the same refund_id and both requests
    # carry the same Idempotency-Key header — the upstream is responsible
    # for the not-debited-twice invariant.
    assert v1.refund_id == v2.refund_id
    for call in route.calls:
        assert call.request.headers["Idempotency-Key"] == str(key)


@respx.mock
async def test_create_refund_409_maps_to_4090(bearer: str) -> None:
    respx.post("https://spring.test/api/v1/orders/ord-9001/refunds").mock(
        return_value=httpx.Response(409, text="in-flight")
    )
    client = httpx.AsyncClient(base_url="https://spring.test")
    with pytest.raises(McpError) as excinfo:
        await _create_refund_impl(
            client,
            CreateRefundArgs(
                order_id="ord-9001",
                amount=Decimal("1.00"),
                reason="test",
                tenant_id="tenant-a",
                idempotency_key=_v4(),
            ),
            bearer,
        )
    await client.aclose()
    assert excinfo.value.error.code == CODE_CONFLICT


@respx.mock
async def test_create_refund_401_maps_to_4030(bearer: str) -> None:
    respx.post("https://spring.test/api/v1/orders/ord-9001/refunds").mock(
        return_value=httpx.Response(401, text="unauthorized")
    )
    client = httpx.AsyncClient(base_url="https://spring.test")
    with pytest.raises(McpError) as excinfo:
        await _create_refund_impl(
            client,
            CreateRefundArgs(
                order_id="ord-9001",
                amount=Decimal("1.00"),
                reason="test",
                tenant_id="tenant-a",
                idempotency_key=_v4(),
            ),
            bearer,
        )
    await client.aclose()
    assert excinfo.value.error.code == CODE_FORBIDDEN


@respx.mock
async def test_create_refund_429_maps_to_4290(bearer: str) -> None:
    respx.post("https://spring.test/api/v1/orders/ord-9001/refunds").mock(
        return_value=httpx.Response(429, text="rate limited")
    )
    client = httpx.AsyncClient(base_url="https://spring.test")
    with pytest.raises(McpError) as excinfo:
        await _create_refund_impl(
            client,
            CreateRefundArgs(
                order_id="ord-9001",
                amount=Decimal("1.00"),
                reason="test",
                tenant_id="tenant-a",
                idempotency_key=_v4(),
            ),
            bearer,
        )
    await client.aclose()
    assert excinfo.value.error.code == CODE_TOO_MANY_REQUESTS
