package com.uptimecrew.expense.api;

import com.fasterxml.jackson.annotation.JsonCreator;
import com.fasterxml.jackson.annotation.JsonProperty;
import java.math.BigDecimal;

/**
 * Request body for POST {@code /api/v1/orders/{orderId}/refunds}.
 *
 * <p>{@code amount} is a {@link BigDecimal} so callers can send Decimal
 * money without float widening. {@code idempotencyKey} in the body is a
 * defensive echo of the {@code Idempotency-Key} HTTP header; both must
 * match for the write to succeed.
 */
public record CreateRefundRequest(
        @JsonProperty("amount") BigDecimal amount,
        @JsonProperty("reason") String reason,
        @JsonProperty("tenant_id") String tenantId,
        @JsonProperty("idempotency_key") String idempotencyKey) {

    @JsonCreator
    public CreateRefundRequest {
        // Canonical compact constructor: Jackson uses @JsonProperty on the
        // record components to bind snake_case JSON to camelCase accessors.
    }
}
