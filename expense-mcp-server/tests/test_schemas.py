"""Schema-level tests: forbid-extra, money precision, UUID v4/v5, tenant allowlist."""

from decimal import Decimal
from typing import Any
from uuid import NAMESPACE_DNS, UUID, uuid4, uuid5

import pytest
from pydantic import ValidationError

from expense_mcp_server.tools.schemas import (
    ChatArgs,
    ChatMessage,
    CreateRefundArgs,
    GetOrderArgs,
    RagArgs,
)


def _v4() -> str:
    return str(uuid4())


@pytest.mark.parametrize(
    "cls, payload",
    [
        (GetOrderArgs, {"order_id": "ord-1", "tenant_id": "tenant-a"}),
        (
            CreateRefundArgs,
            {
                "order_id": "ord-1",
                "amount": Decimal("10.00"),
                "reason": "dupe charge",
                "tenant_id": "tenant-a",
                "idempotency_key": _v4(),
            },
        ),
        (
            ChatArgs,
            {
                "messages": [{"role": "user", "content": "hi"}],
                "max_tokens": 32,
                "tenant_id": "tenant-a",
            },
        ),
        (
            RagArgs,
            {"question": "is a laptop deductible?", "tenant_id": "tenant-a", "top_k": 3},
        ),
    ],
)
def test_json_schema_forbids_additional_properties(
    cls: type[Any], payload: dict[str, object]
) -> None:
    schema = cls.model_json_schema()
    # Rubric: every input schema must declare additionalProperties=false.
    assert schema["additionalProperties"] is False


@pytest.mark.parametrize(
    "cls, payload",
    [
        (
            GetOrderArgs,
            {"order_id": "ord-1", "tenant_id": "tenant-a", "extra": "nope"},
        ),
        (
            CreateRefundArgs,
            {
                "order_id": "ord-1",
                "amount": Decimal("1.00"),
                "reason": "dupe charge",
                "tenant_id": "tenant-a",
                "idempotency_key": _v4(),
                "surprise": True,
            },
        ),
    ],
)
def test_extra_fields_rejected(cls: type[Any], payload: dict[str, object]) -> None:
    with pytest.raises(ValidationError):
        cls(**payload)


def test_amount_rejects_negative() -> None:
    with pytest.raises(ValidationError):
        CreateRefundArgs(
            order_id="ord-1",
            amount=Decimal("-1.00"),
            reason="dupe",
            tenant_id="tenant-a",
            idempotency_key=_v4(),
        )


def test_amount_rejects_more_than_two_decimals() -> None:
    with pytest.raises(ValidationError):
        CreateRefundArgs(
            order_id="ord-1",
            amount=Decimal("1.005"),
            reason="dupe",
            tenant_id="tenant-a",
            idempotency_key=_v4(),
        )


def test_idempotency_key_accepts_uuid_v4() -> None:
    # Interactive callers keep minting a fresh random key per attempt.
    key = _v4()
    args = CreateRefundArgs(
        order_id="ord-1",
        amount=Decimal("1.00"),
        reason="dupe charge",
        tenant_id="tenant-a",
        idempotency_key=key,
    )
    assert args.idempotency_key.version == 4


def test_idempotency_key_accepts_uuid_v5() -> None:
    # W7D5 expense-agent-svc derives a deterministic v5 from
    # (thread_id | tool_name | canonical args hash) so a checkpoint
    # replay produces the same key and the ledger deduplicates the retry.
    v5 = uuid5(NAMESPACE_DNS, "thread-1|orders.create_refund|abcdef")
    args = CreateRefundArgs(
        order_id="ord-1",
        amount=Decimal("1.00"),
        reason="dupe charge",
        tenant_id="tenant-a",
        idempotency_key=str(v5),
    )
    assert args.idempotency_key.version == 5
    # Deterministic: same inputs produce the same UUID.
    v5_again = uuid5(NAMESPACE_DNS, "thread-1|orders.create_refund|abcdef")
    assert v5 == v5_again


def test_idempotency_key_rejects_v3() -> None:
    # A v3 UUID is deterministic but not on the allow-list.
    v3 = str(UUID("6fa459ea-ee8a-3ca4-894e-db77e160355e"))
    with pytest.raises(ValidationError):
        CreateRefundArgs(
            order_id="ord-1",
            amount=Decimal("1.00"),
            reason="dupe charge",
            tenant_id="tenant-a",
            idempotency_key=v3,
        )


def test_idempotency_key_rejects_v1() -> None:
    # v1 leaks host MAC; not accepted.
    v1 = str(UUID("c232ab00-9414-11ec-b3c8-9f6bdeced846"))
    with pytest.raises(ValidationError):
        CreateRefundArgs(
            order_id="ord-1",
            amount=Decimal("1.00"),
            reason="dupe charge",
            tenant_id="tenant-a",
            idempotency_key=v1,
        )


def test_idempotency_key_rejects_malformed() -> None:
    with pytest.raises(ValidationError):
        CreateRefundArgs(
            order_id="ord-1",
            amount=Decimal("1.00"),
            reason="dupe charge",
            tenant_id="tenant-a",
            idempotency_key="not-a-uuid",
        )


def test_tenant_id_allowlist() -> None:
    with pytest.raises(ValidationError):
        GetOrderArgs(order_id="ord-1", tenant_id="tenant-zzz")


def test_chat_requires_at_least_one_message() -> None:
    with pytest.raises(ValidationError):
        ChatArgs(messages=[], max_tokens=32, tenant_id="tenant-a")


def test_chat_message_role_constrained() -> None:
    with pytest.raises(ValidationError):
        ChatMessage(role="root", content="hi")


def test_rag_top_k_bounds() -> None:
    with pytest.raises(ValidationError):
        RagArgs(question="hi?", tenant_id="tenant-a", top_k=0)
    with pytest.raises(ValidationError):
        RagArgs(question="hi?", tenant_id="tenant-a", top_k=21)


def test_rag_question_length_bounds() -> None:
    with pytest.raises(ValidationError):
        RagArgs(question="x", tenant_id="tenant-a", top_k=3)
