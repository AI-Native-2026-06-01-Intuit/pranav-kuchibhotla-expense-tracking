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

    public Transaction(String id, String accountId, BigDecimal amount, String merchantName, LocalDate occurredOn) {
        Objects.requireNonNull(id, "id");
        Objects.requireNonNull(accountId, "accountId");
        Objects.requireNonNull(amount, "amount");
        Objects.requireNonNull(merchantName, "merchantName");
        Objects.requireNonNull(occurredOn, "occurredOn");
        if (id.isBlank()) {
            throw new IllegalArgumentException("id must not be blank");
        }
        if (accountId.isBlank()) {
            throw new IllegalArgumentException("accountId must not be blank");
        }
        if (merchantName.isBlank()) {
            throw new IllegalArgumentException("merchantName must not be blank");
        }
        if (amount.signum() < 0) {
            throw new IllegalArgumentException("amount must not be negative");
        }
        this.id = id;
        this.accountId = accountId;
        this.amount = amount.setScale(2, RoundingMode.HALF_UP);
        this.merchantName = merchantName;
        this.occurredOn = occurredOn;
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
    public boolean equals(Object o) {
        if (this == o) return true;
        if (!(o instanceof Transaction other)) return false;
        return id.equals(other.id)
                && accountId.equals(other.accountId)
                && amount.equals(other.amount)
                && merchantName.equals(other.merchantName)
                && occurredOn.equals(other.occurredOn);
    }

    @Override
    public int hashCode() {
        return Objects.hash(id, accountId, amount, merchantName, occurredOn);
    }

    @Override
    public String toString() {
        return "Transaction{id=" + id
                + ", accountId=" + accountId
                + ", amount=" + amount
                + ", merchantName=" + merchantName
                + ", occurredOn=" + occurredOn
                + '}';
    }
}
