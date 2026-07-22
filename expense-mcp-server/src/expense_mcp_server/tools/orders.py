"""Orders tools: ``orders.get_order`` and ``orders.create_refund``.

Both tools are thin adapters over the Spring surface at
``EXPENSE_MCP_ORDERS_SVC_URL``. The refund handler enforces the
idempotency contract at two layers: the schema requires a UUID v4, and
the request payload sends the same key in both the JSON body and the
``Idempotency-Key`` HTTP header so the upstream store rejects any
header/body drift.
"""

import time
from decimal import Decimal
from typing import Any

import httpx
from langsmith import traceable
from mcp.server.fastmcp import Context

from ..app import deps_from, mcp
from ..auth import assert_tenant_matches, bearer_for_upstream
from ..errors import map_http
from ..telemetry import get_logger
from .schemas import CreateRefundArgs, GetOrderArgs, OrderView, RefundView

_log = get_logger("expense_mcp_server.tools.orders")


_GET_ORDER_DESCRIPTION = (
    "Fetch a single order by id, scoped to the caller's tenant. "
    "Use this tool when you already have an order id (for example, a "
    "refund workflow, a status audit, or when Claude was given the id "
    "in the chat context) and need the current total, status, and "
    "creation timestamp. Do NOT use this tool to enumerate orders, "
    "search by customer, or infer analytics — it returns exactly one "
    "record and 404s otherwise. The output is bounded to five fields; "
    "monetary totals are Decimal so downstream arithmetic stays exact. "
    "Example: orders.get_order(order_id='ord-synth-9001', "
    "tenant_id='tenant-a') returns the seeded synthetic order."
)


_CREATE_REFUND_DESCRIPTION = (
    "Create a refund for an existing order. Use this tool when the "
    "caller has explicit permission to debit the ledger and has "
    "supplied a fresh UUID v4 idempotency_key. The same (order_id, "
    "idempotency_key) pair returns the same refund_id on repeat calls "
    "and never debits the ledger twice — that is the whole point of "
    "the key. Do NOT reuse a key across logically-different refunds, "
    "and do NOT invent a key without persisting it on the caller "
    "side. Requires scope orders.write. Example: "
    "orders.create_refund(order_id='ord-synth-9001', amount='10.00', "
    "reason='duplicate charge', tenant_id='tenant-a', "
    "idempotency_key='<uuid4>') returns a RefundView."
)


def _tenant_header(tenant_id: str) -> dict[str, str]:
    return {"X-Tenant-Id": tenant_id}


def _auth_header(deps_bearer: str) -> dict[str, str]:
    token = bearer_for_upstream(deps_bearer)
    if not token:
        return {}
    return {"Authorization": f"Bearer {token}"}


async def _get_order_impl(client: httpx.AsyncClient, args: GetOrderArgs, bearer: str) -> OrderView:
    started = time.perf_counter()
    _log.info("tool.invoke.start", tool="orders.get_order", tenant_id=args.tenant_id)
    resp = await client.get(
        f"/api/v1/orders/{args.order_id}",
        headers={**_tenant_header(args.tenant_id), **_auth_header(bearer)},
    )
    duration_ms = int((time.perf_counter() - started) * 1000)
    if resp.status_code != 200:
        err = map_http(resp.status_code, resp.text)
        _log.warning(
            "tool.invoke.end",
            tool="orders.get_order",
            tenant_id=args.tenant_id,
            duration_ms=duration_ms,
            cost_usd_minor=0,
            mcp_error_code=err.error.code,
        )
        raise err
    body: dict[str, Any] = resp.json()
    view = OrderView(
        order_id=str(body["orderId"]),
        tenant_id=str(body["tenantId"]),
        total=Decimal(str(body["total"])),
        status=body["status"],
        created_at=body.get("createdAt"),
    )
    _log.info(
        "tool.invoke.end",
        tool="orders.get_order",
        tenant_id=args.tenant_id,
        duration_ms=duration_ms,
        cost_usd_minor=0,
    )
    return view


async def _create_refund_impl(
    client: httpx.AsyncClient, args: CreateRefundArgs, bearer: str
) -> RefundView:
    started = time.perf_counter()
    _log.info("tool.invoke.start", tool="orders.create_refund", tenant_id=args.tenant_id)
    payload = {
        # Money as a JSON string so a JSON parser cannot silently widen
        # to float on either side of the wire.
        "amount": str(args.amount),
        "reason": args.reason,
        "tenant_id": args.tenant_id,
        "idempotency_key": str(args.idempotency_key),
    }
    resp = await client.post(
        f"/api/v1/orders/{args.order_id}/refunds",
        json=payload,
        headers={
            "Idempotency-Key": str(args.idempotency_key),
            **_auth_header(bearer),
        },
    )
    duration_ms = int((time.perf_counter() - started) * 1000)
    if resp.status_code != 200:
        err = map_http(resp.status_code, resp.text)
        _log.warning(
            "tool.invoke.end",
            tool="orders.create_refund",
            tenant_id=args.tenant_id,
            duration_ms=duration_ms,
            cost_usd_minor=0,
            mcp_error_code=err.error.code,
        )
        raise err
    body: dict[str, Any] = resp.json()
    view = RefundView(
        refund_id=str(body["refundId"]),
        order_id=str(body["orderId"]),
        amount=Decimal(str(body["amount"])),
        reason=str(body["reason"]),
        status=body["status"],
    )
    _log.info(
        "tool.invoke.end",
        tool="orders.create_refund",
        tenant_id=args.tenant_id,
        duration_ms=duration_ms,
        cost_usd_minor=0,
    )
    return view


@mcp.tool(name="orders.get_order", description=_GET_ORDER_DESCRIPTION)
@traceable(name="orders.get_order", run_type="tool")
async def get_order(order_id: str, tenant_id: str, ctx: Context) -> OrderView:  # type: ignore[type-arg]
    args = GetOrderArgs(order_id=order_id, tenant_id=tenant_id)
    assert_tenant_matches(args.tenant_id)
    deps = deps_from(ctx)
    bearer = deps.settings.bearer_jwt.get_secret_value()
    return await _get_order_impl(deps.orders_client, args, bearer)


@mcp.tool(name="orders.create_refund", description=_CREATE_REFUND_DESCRIPTION)
@traceable(name="orders.create_refund", run_type="tool")
async def create_refund(
    order_id: str,
    amount: str,
    reason: str,
    tenant_id: str,
    idempotency_key: str,
    ctx: Context,  # type: ignore[type-arg]
) -> RefundView:
    args = CreateRefundArgs(
        order_id=order_id,
        amount=Decimal(amount),
        reason=reason,
        tenant_id=tenant_id,
        idempotency_key=idempotency_key,
    )
    assert_tenant_matches(args.tenant_id)
    deps = deps_from(ctx)
    bearer = deps.settings.bearer_jwt.get_secret_value()
    return await _create_refund_impl(deps.orders_client, args, bearer)


__all__ = ["create_refund", "get_order"]
