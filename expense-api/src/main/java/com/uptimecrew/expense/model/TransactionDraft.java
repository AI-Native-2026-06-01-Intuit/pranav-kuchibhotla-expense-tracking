package com.uptimecrew.expense.model;

import java.math.BigDecimal;
import java.math.RoundingMode;
import java.time.LocalDate;
import java.util.Objects;

public final class TransactionDraft {

    private final String id;
    private final BigDecimal amount;
    private final String merchantName;
    private final LocalDate occurredOn;

    public TransactionDraft(
            String id,
            BigDecimal amount,
            String merchantName,
            LocalDate occurredOn) {

        this.id = requireNonBlank(id, "id");
        this.amount = normalizeAmount(amount);
        this.merchantName = requireNonBlank(merchantName, "merchantName");
        this.occurredOn = Objects.requireNonNull(occurredOn, "occurredOn must not be null");
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

    public String getId() {
        return id;
    }

    public BigDecimal getAmount() {
        return amount;
    }

    public String getMerchantName() {
        return merchantName;
    }

    public LocalDate getOccurredOn() {
        return occurredOn;
    }

    @Override
    public boolean equals(Object other) {
        if (this == other) {
            return true;
        }
        if (!(other instanceof TransactionDraft that)) {
            return false;
        }
        return id.equals(that.id)
                && amount.equals(that.amount)
                && merchantName.equals(that.merchantName)
                && occurredOn.equals(that.occurredOn);
    }

    @Override
    public int hashCode() {
        return Objects.hash(id, amount, merchantName, occurredOn);
    }

    @Override
    public String toString() {
        return "TransactionDraft{"
                + "id='" + id + '\''
                + ", amount=" + amount
                + ", merchantName='" + merchantName + '\''
                + ", occurredOn=" + occurredOn
                + '}';
    }
}
