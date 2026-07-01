package com.uptimecrew.expense.model;

import java.math.BigDecimal;
import java.math.RoundingMode;
import java.time.LocalDate;
import java.util.Objects;

/**
 * Immutable transaction imported from a linked financial account.
 */
public record Transaction(
        String id,
        String accountId,
        BigDecimal amount,
        String merchantName,
        LocalDate occurredOn) {

    public Transaction {
        id = requireNonBlank(id, "id");
        accountId = requireNonBlank(accountId, "accountId");
        amount = normalizeAmount(amount);
        merchantName = requireNonBlank(merchantName, "merchantName");
        occurredOn = Objects.requireNonNull(occurredOn, "occurredOn must not be null");
    }

    private static String requireNonBlank(String value, String fieldName) {
        Objects.requireNonNull(value, fieldName + " must not be null");
        if (value.isBlank()) {
            throw new IllegalArgumentException(fieldName + " must be non-blank");
        }
        return value;
    }

    private static BigDecimal normalizeAmount(BigDecimal value) {
        Objects.requireNonNull(value, "amount must not be null");
        if (value.signum() < 0) {
            throw new IllegalArgumentException("amount must be >= 0");
        }
        return value.setScale(2, RoundingMode.HALF_UP);
    }
}
