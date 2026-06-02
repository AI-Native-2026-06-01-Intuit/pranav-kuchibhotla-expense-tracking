package com.uptimecrew.expense.model;

import java.math.BigDecimal;
import java.math.RoundingMode;
import java.time.LocalDate;
import java.util.Objects;

public final class Transaction {

    private final String id;
    private final String accountId;
    private final BigDecimal amount;
    private final String merchantName;
    private final LocalDate occurredOn;

    public Transaction(
            String id,
            String accountId,
            BigDecimal amount,
            String merchantName,
            LocalDate occurredOn) {

        this.id = requireNonBlank(id, "id");
        this.accountId = requireNonBlank(accountId, "accountId");
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

    public String id() {
        return id;
    }

    public String accountId() {
        return accountId;
    }

    public BigDecimal amount() {
        return amount;
    }

    public String merchantName() {
        return merchantName;
    }

    public LocalDate occurredOn() {
        return occurredOn;
    }

    @Override
    public boolean equals(Object other) {
        if (this == other) {
            return true;
        }
        if (!(other instanceof Transaction that)) {
            return false;
        }
        return id.equals(that.id)
                && accountId.equals(that.accountId)
                && amount.equals(that.amount)
                && merchantName.equals(that.merchantName)
                && occurredOn.equals(that.occurredOn);
    }

    @Override
    public int hashCode() {
        return Objects.hash(id, accountId, amount, merchantName, occurredOn);
    }

    @Override
    public String toString() {
        return "Transaction{"
                + "id='" + id + '\''
                + ", accountId='" + accountId + '\''
                + ", amount=" + amount
                + ", merchantName='" + merchantName + '\''
                + ", occurredOn=" + occurredOn
                + '}';
    }
}
