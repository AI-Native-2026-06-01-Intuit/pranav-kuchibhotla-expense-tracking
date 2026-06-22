package com.uptimecrew.expense.readmodel;

import java.io.Serializable;
import java.math.BigDecimal;
import java.time.Instant;
import java.util.ArrayList;
import java.util.List;
import org.springframework.data.annotation.Id;
import org.springframework.data.mongodb.core.index.Indexed;
import org.springframework.data.mongodb.core.mapping.Document;

import com.uptimecrew.expense.consumer.MerchantClassifiedEvent;

/**
 * Denormalized MongoDB read model that mirrors the JPA
 * {@code Merchant} aggregate. Unlike the JPA entity — which lazy-loads
 * {@code MerchantTransaction} rows through a one-to-many association —
 * this document embeds the transaction collection directly so a single
 * Mongo read returns the merchant and all of its transactions in one
 * round trip, with no second query and no JPA session needed.
 */
@Document(collection = "merchants")
public final class MerchantReadModel implements Serializable {

    private static final long serialVersionUID = 1L;

    @Id
    private String id;

    private String displayName;

    private String normalizedName;

    private String merchantKind;

    @Indexed
    private String mccCode;

    private Instant createdAt;

    private List<EmbeddedTransaction> transactions;

    public MerchantReadModel() {
    }

    /**
     * Single-arg constructor used by the Kafka consumer when an event
     * arrives for an aggregate id that has no existing document yet.
     * The remaining fields are populated by {@link #applyEvent}.
     */
    public MerchantReadModel(String id) {
        this.id = id;
        this.transactions = new ArrayList<>();
    }

    public MerchantReadModel(String id,
                             String displayName,
                             String normalizedName,
                             String merchantKind,
                             String mccCode,
                             Instant createdAt,
                             List<EmbeddedTransaction> transactions) {
        this.id = id;
        this.displayName = displayName;
        this.normalizedName = normalizedName;
        this.merchantKind = merchantKind;
        this.mccCode = mccCode;
        this.createdAt = createdAt;
        this.transactions = transactions != null ? transactions : new ArrayList<>();
    }

    public String getId() {
        return id;
    }

    public String getDisplayName() {
        return displayName;
    }

    public String getNormalizedName() {
        return normalizedName;
    }

    public String getMerchantKind() {
        return merchantKind;
    }

    public String getMccCode() {
        return mccCode;
    }

    public Instant getCreatedAt() {
        return createdAt;
    }

    public List<EmbeddedTransaction> getTransactions() {
        return transactions;
    }

    /**
     * Apply a {@link MerchantClassifiedEvent} to this document. Idempotent:
     * applying the same event twice yields the same field values, since each
     * assignment overwrites with the event's value rather than appending.
     */
    public void applyEvent(MerchantClassifiedEvent event) {
        this.id = event.aggregateId();
        this.displayName = event.displayName();
        this.normalizedName = event.normalizedName();
        this.mccCode = event.mccCode();
        this.merchantKind = event.classificationKind();
    }

    public static final class EmbeddedTransaction implements Serializable {

        private static final long serialVersionUID = 1L;

        private String id;
        private String accountId;
        private BigDecimal amount;
        private String transactionKind;
        private Instant occurredAt;
        private Instant classifiedAt;

        public EmbeddedTransaction() {
        }

        public EmbeddedTransaction(String id,
                                   String accountId,
                                   BigDecimal amount,
                                   String transactionKind,
                                   Instant occurredAt,
                                   Instant classifiedAt) {
            this.id = id;
            this.accountId = accountId;
            this.amount = amount;
            this.transactionKind = transactionKind;
            this.occurredAt = occurredAt;
            this.classifiedAt = classifiedAt;
        }

        public String getId() {
            return id;
        }

        public String getAccountId() {
            return accountId;
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
    }
}
