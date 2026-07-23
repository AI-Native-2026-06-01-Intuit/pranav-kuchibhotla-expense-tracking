"""Pydantic v2 input/output schemas for the four expense MCP tools.

Every input model sets ``extra="forbid"`` so a caller that includes an
unexpected field gets an immediate schema error instead of a silent
drop. Every money field is :class:`decimal.Decimal` — never ``float`` —
so the wire representation and the domain-layer arithmetic agree on
scale + rounding.
"""

from datetime import datetime
from decimal import Decimal
from typing import Annotated, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator

# Tenants allowed to appear in tool arguments. Kept intentionally small
# for the W7D4 synthetic surface; a production catalog would source the
# list from an identity claim, not a hard-coded enum.
ALLOWED_TENANTS = ("tenant-a", "tenant-b", "tenant-c")

TenantId = Annotated[str, Field(min_length=1)]


class _Strict(BaseModel):
    """Base class enforcing forbid-extra and immutability at the schema layer."""

    model_config = ConfigDict(extra="forbid", frozen=True)


def _validate_tenant(value: str) -> str:
    if value not in ALLOWED_TENANTS:
        raise ValueError(f"unsupported tenant_id: {value!r}")
    return value


# -----------------------------------------------------------------------------
# orders.get_order
# -----------------------------------------------------------------------------


class GetOrderArgs(_Strict):
    order_id: Annotated[str, Field(min_length=1, max_length=128)]
    tenant_id: TenantId

    @field_validator("tenant_id")
    @classmethod
    def _t(cls, v: str) -> str:
        return _validate_tenant(v)


class OrderView(_Strict):
    order_id: str
    tenant_id: str
    total: Decimal
    status: Literal["OPEN", "REFUNDED", "PARTIALLY_REFUNDED", "CANCELLED"]
    created_at: datetime | None = None


# -----------------------------------------------------------------------------
# orders.create_refund
# -----------------------------------------------------------------------------


class CreateRefundArgs(_Strict):
    order_id: Annotated[str, Field(min_length=1, max_length=128)]
    amount: Decimal
    reason: Annotated[str, Field(min_length=4, max_length=200)]
    tenant_id: TenantId
    # Accept UUID v4 (interactive callers minting a fresh random key) OR
    # UUID v5 (W7D5 expense-agent-svc deriving a deterministic key from
    # thread_id + tool_name + canonical args hash so a checkpoint replay
    # produces the same key and the upstream ledger deduplicates the
    # retry). Any other UUID version is rejected: v1 leaks the MAC, v2
    # is not portable, v3 is the MD5 twin of v5 and buys nothing extra.
    idempotency_key: UUID

    @field_validator("tenant_id")
    @classmethod
    def _t(cls, v: str) -> str:
        return _validate_tenant(v)

    @field_validator("amount")
    @classmethod
    def _positive_two_dp(cls, v: Decimal) -> Decimal:
        if v <= 0:
            raise ValueError("amount must be > 0")
        # Reject more than two decimal places up-front so the upstream
        # BigDecimal never has to round money silently.
        exponent = v.normalize().as_tuple().exponent
        if isinstance(exponent, int) and exponent < -2:
            raise ValueError("amount cannot have more than 2 decimal places")
        return v

    @field_validator("idempotency_key")
    @classmethod
    def _accept_v4_or_v5(cls, v: UUID) -> UUID:
        if v.version not in (4, 5):
            raise ValueError("idempotency_key must be a UUID v4 or v5")
        return v


class RefundView(_Strict):
    refund_id: str
    order_id: str
    amount: Decimal
    reason: str
    status: Literal["PENDING", "SETTLED", "FAILED"]


# -----------------------------------------------------------------------------
# llm.chat
# -----------------------------------------------------------------------------


class ChatMessage(_Strict):
    role: Literal["system", "user", "assistant"]
    content: Annotated[str, Field(min_length=1, max_length=8000)]


class ChatArgs(_Strict):
    messages: Annotated[list[ChatMessage], Field(min_length=1, max_length=32)]
    max_tokens: Annotated[int, Field(ge=1, le=2048)] = 256
    tenant_id: TenantId

    @field_validator("tenant_id")
    @classmethod
    def _t(cls, v: str) -> str:
        return _validate_tenant(v)


class ChatAnswer(_Strict):
    text: str
    model: str
    usage_input_tokens: int = 0
    usage_output_tokens: int = 0
    cost_usd_minor: int = 0


# -----------------------------------------------------------------------------
# rag.retrieve_and_generate
# -----------------------------------------------------------------------------


class RagArgs(_Strict):
    question: Annotated[str, Field(min_length=2, max_length=2000)]
    tenant_id: TenantId
    top_k: Annotated[int, Field(ge=1, le=20)] = 6

    @field_validator("tenant_id")
    @classmethod
    def _t(cls, v: str) -> str:
        return _validate_tenant(v)


class Citation(_Strict):
    chunk_id: str
    doc_id: str
    # Similarity/rerank score is a fundamentally floating-point value;
    # float is correct here, unlike money.
    score: float


class RagAnswer(_Strict):
    answer: str
    citations: list[Citation]
    coverage: float
    rerank_timed_out: bool
