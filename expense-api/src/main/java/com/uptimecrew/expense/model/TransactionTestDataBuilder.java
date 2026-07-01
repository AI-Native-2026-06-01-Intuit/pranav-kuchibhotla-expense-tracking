package com.uptimecrew.expense.model;

import java.math.BigDecimal;
import java.time.LocalDate;

/**
 * Fluent test data builder for {@link Transaction}. Starts from a set of valid
 * defaults and allows tests to override only the fields relevant to the case
 * under test, keeping construction noise out of the test body.
 */
public final class TransactionTestDataBuilder {

    private String id = "txn-builder-001";
    private String accountId = "acct-builder-001";
    private BigDecimal amount = new BigDecimal("42.00");
    private String merchantName = "Office Depot";
    private LocalDate occurredOn = LocalDate.of(2026, 3, 1);

    private TransactionTestDataBuilder() {}

    /** Starts a new builder pre-populated with valid default values. */
    public static TransactionTestDataBuilder aTransaction() {
        return new TransactionTestDataBuilder();
    }

    public TransactionTestDataBuilder withId(String value) {
        this.id = value;
        return this;
    }

    public TransactionTestDataBuilder withAccountId(String value) {
        this.accountId = value;
        return this;
    }

    public TransactionTestDataBuilder withAmount(BigDecimal value) {
        this.amount = value;
        return this;
    }

    public TransactionTestDataBuilder withMerchantName(String value) {
        this.merchantName = value;
        return this;
    }

    public TransactionTestDataBuilder withOccurredOn(LocalDate value) {
        this.occurredOn = value;
        return this;
    }

    public Transaction build() {
        return new Transaction(id, accountId, amount, merchantName, occurredOn);
    }
}
