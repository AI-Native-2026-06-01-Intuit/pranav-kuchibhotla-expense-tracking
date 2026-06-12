package com.uptimecrew.expense.entity;

import jakarta.persistence.CascadeType;
import jakarta.persistence.Column;
import jakarta.persistence.Entity;
import jakarta.persistence.FetchType;
import jakarta.persistence.Id;
import jakarta.persistence.OneToMany;
import jakarta.persistence.Table;
import java.time.Instant;
import java.util.ArrayList;
import java.util.List;
import java.util.Objects;

/**
 * JPA mapping of the {@code expense.merchant} table (W2D1 schema).
 */
@Entity
@Table(schema = "expense", name = "merchant")
public class Merchant {

    @Id
    @Column(name = "id", length = 64, nullable = false)
    private String id;

    @Column(name = "display_name", nullable = false)
    private String displayName;

    @Column(name = "normalized_name", nullable = false)
    private String normalizedName;

    @Column(name = "merchant_kind", nullable = false)
    private String merchantKind;

    @Column(name = "created_at", nullable = false, insertable = false, updatable = false)
    private Instant createdAt;

    @OneToMany(mappedBy = "merchant", fetch = FetchType.LAZY,
               cascade = CascadeType.ALL, orphanRemoval = true)
    private List<MerchantTransaction> transactions = new ArrayList<>();

    protected Merchant() {
    }

    public Merchant(String id, String displayName, String normalizedName, String merchantKind) {
        this.id = Objects.requireNonNull(id, "id");
        this.displayName = Objects.requireNonNull(displayName, "displayName");
        this.normalizedName = Objects.requireNonNull(normalizedName, "normalizedName");
        this.merchantKind = Objects.requireNonNull(merchantKind, "merchantKind");
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

    public Instant getCreatedAt() {
        return createdAt;
    }

    public List<MerchantTransaction> getTransactions() {
        return transactions;
    }

    public void addTransaction(MerchantTransaction tx) {
        transactions.add(tx);
        tx.setMerchantInternal(this);
    }

    public void removeTransaction(MerchantTransaction tx) {
        transactions.remove(tx);
        tx.setMerchantInternal(null);
    }

    @Override
    public boolean equals(Object o) {
        if (this == o) return true;
        if (!(o instanceof Merchant other)) return false;
        return Objects.equals(id, other.id);
    }

    @Override
    public int hashCode() {
        return Objects.hash(id);
    }

    @Override
    public String toString() {
        return "Merchant{id=" + id + ", normalizedName=" + normalizedName + "}";
    }
}
