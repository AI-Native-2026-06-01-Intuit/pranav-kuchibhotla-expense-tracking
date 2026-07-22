package com.uptimecrew.expense.api;

import java.math.BigDecimal;

/**
 * Response DTO for a settled refund. The MCP adapter maps this shape
 * onto its pre-shaped {@code RefundView} tool output.
 */
public record RefundView(
        String refundId,
        String orderId,
        BigDecimal amount,
        String reason,
        String status) {
}
