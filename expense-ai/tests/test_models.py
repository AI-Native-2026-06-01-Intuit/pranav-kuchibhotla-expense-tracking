"""Tests for the Pydantic boundary models."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path

import pytest
from pydantic import ValidationError

from expense_ai.models import (
    DeductionClassifyRequest,
    DeductionClassifyResult,
    Merchant,
)


def test_merchant_round_trip_matches_java_fixture(merchant_json_bytes: bytes) -> None:
    merchant = Merchant.model_validate_json(merchant_json_bytes)

    assert merchant.id == "merchant-001"
    assert merchant.tenant_id == "tenant-synth"
    assert merchant.amount == Decimal("123.45")

    dumped = json.loads(merchant.model_dump_json(by_alias=True))
    expected = json.loads(merchant_json_bytes)
    assert dumped == expected


def test_merchant_forbids_extra_fields(merchant_json_bytes: bytes) -> None:
    payload = json.loads(merchant_json_bytes)
    payload["surprise"] = "nope"
    with pytest.raises(ValidationError):
        Merchant.model_validate(payload)


@pytest.mark.parametrize(
    "bad_tenant",
    ["", "acct-1", "team-synth", "TENANT-abc"],
)
def test_merchant_tenant_id_validator(bad_tenant: str) -> None:
    with pytest.raises(ValidationError):
        Merchant.model_validate(
            {
                "id": "m-1",
                "tenantId": bad_tenant,
                "name": "x",
                "category": "misc",
                "amount": "10.00",
                "createdAt": "2026-01-15T12:00:00Z",
            }
        )


def test_merchant_rejects_negative_amount() -> None:
    with pytest.raises(ValidationError):
        Merchant.model_validate(
            {
                "id": "m-1",
                "tenantId": "tenant-synth",
                "name": "x",
                "category": "misc",
                "amount": "-0.01",
                "createdAt": "2026-01-15T12:00:00Z",
            }
        )


def test_merchant_tmp_path_round_trip(tmp_path: Path) -> None:
    merchant = Merchant(
        id="merchant-77",
        tenant_id="tenant-synth",
        name="Blue Bottle",
        category="meals",
        amount=Decimal("9.75"),
        created_at=datetime(2026, 2, 1, 8, 30, tzinfo=UTC),
    )
    path = tmp_path / "merchant.json"
    path.write_text(merchant.model_dump_json(by_alias=True))
    reloaded = Merchant.model_validate_json(path.read_bytes())
    assert reloaded == merchant


def test_deduction_request_correlation_id_validator() -> None:
    with pytest.raises(ValidationError):
        DeductionClassifyRequest.model_validate(
            {
                "correlationId": "abc-1",
                "merchant": {
                    "id": "m-1",
                    "tenantId": "tenant-synth",
                    "name": "x",
                    "category": "misc",
                    "amount": "10.00",
                    "createdAt": "2026-01-15T12:00:00Z",
                },
                "modelId": "model-x",
            }
        )


def test_deduction_result_high_confidence_requires_rationale() -> None:
    with pytest.raises(ValidationError):
        DeductionClassifyResult.model_validate(
            {
                "correlationId": "corr-1",
                "merchantId": "m-1",
                "label": "office_supplies",
                "confidence": "0.95",
                "deductible": True,
                "rationale": "too short",
            }
        )


def test_deduction_result_low_confidence_short_rationale_allowed() -> None:
    result = DeductionClassifyResult.model_validate(
        {
            "correlationId": "corr-1",
            "merchantId": "m-1",
            "label": "office_supplies",
            "confidence": "0.30",
            "deductible": False,
            "rationale": "unsure",
        }
    )
    assert result.confidence == Decimal("0.30")
