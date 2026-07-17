"""Pydantic v2 boundary models for the Java <-> Python wire contract."""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


class Merchant(BaseModel):  # type: ignore[explicit-any]
    """A merchant record as it crosses the Java/Python boundary."""

    model_config = ConfigDict(
        extra="forbid",
        frozen=True,
        populate_by_name=True,
    )

    id: str
    tenant_id: str = Field(alias="tenantId")
    name: str
    category: str
    amount: Decimal = Field(ge=Decimal("0"), max_digits=14, decimal_places=2)
    created_at: datetime = Field(alias="createdAt")

    @field_validator("tenant_id")
    @classmethod
    def _tenant_id_prefix(cls, value: str) -> str:
        if not value.startswith("tenant-"):
            raise ValueError("tenant_id must start with 'tenant-'")
        return value


class DeductionClassifyRequest(BaseModel):  # type: ignore[explicit-any]
    """Envelope sent from the Python sidecar to the LLM proxy."""

    model_config = ConfigDict(
        extra="forbid",
        frozen=True,
        populate_by_name=True,
    )

    correlation_id: str = Field(alias="correlationId")
    merchant: Merchant
    model_id: str = Field(alias="modelId")
    include_rationale: bool = Field(default=True, alias="includeRationale")

    @field_validator("correlation_id")
    @classmethod
    def _correlation_id_prefix(cls, value: str) -> str:
        if not value.startswith("corr-"):
            raise ValueError("correlation_id must start with 'corr-'")
        return value


class DeductionClassifyResult(BaseModel):  # type: ignore[explicit-any]
    """Result returned from the LLM proxy back to the sidecar caller."""

    model_config = ConfigDict(
        extra="forbid",
        frozen=True,
        populate_by_name=True,
    )

    correlation_id: str = Field(alias="correlationId")
    merchant_id: str = Field(alias="merchantId")
    label: str
    confidence: Decimal = Field(ge=Decimal("0"), le=Decimal("1"))
    deductible: bool
    rationale: str

    @field_validator("correlation_id")
    @classmethod
    def _correlation_id_prefix(cls, value: str) -> str:
        if not value.startswith("corr-"):
            raise ValueError("correlation_id must start with 'corr-'")
        return value

    @model_validator(mode="after")
    def _high_confidence_requires_rationale(self) -> DeductionClassifyResult:
        if self.confidence >= Decimal("0.90") and len(self.rationale) < 16:
            raise ValueError(
                "high-confidence result (>=0.90) requires rationale of at least 16 chars"
            )
        return self
