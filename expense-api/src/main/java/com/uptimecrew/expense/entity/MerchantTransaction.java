package com.uptimecrew.expense.entity;

import jakarta.persistence.Column;
import jakarta.persistence.Entity;
import jakarta.persistence.FetchType;
import jakarta.persistence.Id;
import jakarta.persistence.JoinColumn;
import jakarta.persistence.ManyToOne;
import jakarta.persistence.Table;
import java.math.BigDecimal;
import java.time.Instant;
import java.util.Objects;

/**
 * JPA mapping of the {@code expense.transaction} table (W2D1 schema).
 * Named {@code MerchantTransaction} because {@code transaction} is a
 * reserved word in many SQL dialects and an overloaded term in Java.
 */
@Entity
@Table(schema = "expense", name = "transaction")
public class MerchantTransaction {

    @Id
    @Column(name = "id", length = 64, nullable = false)
    private String id;

    @Column(name = "account_id", nullable = false)
    private String accountId;

    @ManyToOne(fetch = FetchType.LAZY, optional = false)
    @JoinColumn(name = "merchant_id", nullable = false)
    private Merchant merchant;

    @Column(name = "matched_rule_id", nullable = true)
    private String matchedRuleId;

    @Column(name = "amount", nullable = false)
    private BigDecimal amount;

    @Column(name = "transaction_kind", nullable = false)
    private String transactionKind;

    @Column(name = "occurred_at", nullable = false)
    private Instant occurredAt;

    @Column(name = "classified_at", nullable = true)
    private Instant classifiedAt;

    @Column(name = "created_at", nullable = false, insertable = false, updatable = false)
    private Instant createdAt;

    protected MerchantTransaction() {
    }

    public MerchantTransaction(String id,
                               String accountId,
                               Merchant merchant,
                               BigDecimal amount,
                               String transactionKind,
                               Instant occurredAt) {
        this.id = Objects.requireNonNull(id, "id");
        this.accountId = Objects.requireNonNull(accountId, "accountId");
        this.merchant = Objects.requireNonNull(merchant, "merchant");
        this.amount = Objects.requireNonNull(amount, "amount");
        this.transactionKind = Objects.requireNonNull(transactionKind, "transactionKind");
        this.occurredAt = Objects.requireNonNull(occurredAt, "occurredAt");
    }

    public String getId() {
        return id;
    }

    public String getAccountId() {
        return accountId;
    }

    public Merchant getMerchant() {
        return merchant;
    }

    public String getMatchedRuleId() {
        return matchedRuleId;
    }

    public BigDecimal getAmount() {
        return amount;
    }

    public String getTransactionKind() {
        return transactionKind;
    }

    public Instant getOccurredAt() {
        return occurredAt;
    }

    public Instant getClassifiedAt() {
        return classifiedAt;
    }

    public Instant getCreatedAt() {
        return createdAt;
    }

    void setMerchantInternal(Merchant merchant) {
        this.merchant = merchant;
    }

    @Override
    public boolean equals(Object o) {
        if (this == o) return true;
        if (!(o instanceof MerchantTransaction other)) return false;
        return Objects.equals(id, other.id);
    }

    @Override
    public int hashCode() {
        return Objects.hash(id);
    }

    @Override
    public String toString() {
        return "MerchantTransaction{id=" + id + ", accountId=" + accountId + ", amount=" + amount + "}";
    }
}
