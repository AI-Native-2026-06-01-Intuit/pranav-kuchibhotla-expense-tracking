package com.uptimecrew.expense.api;

import java.math.BigDecimal;
import java.time.Instant;

/**
 * Read-model DTO for a synthetic order. Amount is serialized as a JSON
 * number backed by {@link BigDecimal} so the MCP adapter can parse it
 * into a Python {@code Decimal} without going through float.
 */
public record OrderView(
        String orderId,
        String tenantId,
        BigDecimal total,
        String status,
        Instant createdAt) {
}
