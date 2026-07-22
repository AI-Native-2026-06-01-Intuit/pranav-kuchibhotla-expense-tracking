package com.uptimecrew.expense.entity;

import jakarta.persistence.Column;
import jakarta.persistence.Entity;
import jakarta.persistence.Id;
import jakarta.persistence.Table;
import java.math.BigDecimal;
import java.time.Instant;
import java.util.Objects;

/**
 * JPA mapping of {@code expense.synthetic_order} (V5 schema).
 *
 * <p>Added for the W7D4 MCP adapter: the capstone repository does not
 * expose a native orders/refunds domain, so we ship a minimal synthetic
 * table that the MCP {@code orders.get_order} tool can point at.
 */
@Entity
@Table(schema = "expense", name = "synthetic_order")
public class SyntheticOrder {

    @Id
    @Column(name = "id", length = 64, nullable = false)
    private String id;

    @Column(name = "tenant_id", nullable = false)
    private String tenantId;

    @Column(name = "total_amount", nullable = false, precision = 12, scale = 2)
    private BigDecimal totalAmount;

    @Column(name = "status", nullable = false)
    private String status;

    @Column(name = "created_at", nullable = false, insertable = false, updatable = false)
    private Instant createdAt;

    protected SyntheticOrder() {
    }

    public SyntheticOrder(String id, String tenantId, BigDecimal totalAmount, String status) {
        this.id = Objects.requireNonNull(id, "id");
        this.tenantId = Objects.requireNonNull(tenantId, "tenantId");
        this.totalAmount = Objects.requireNonNull(totalAmount, "totalAmount");
        this.status = Objects.requireNonNull(status, "status");
    }

    public String getId() {
        return id;
    }

    public String getTenantId() {
        return tenantId;
    }

    public BigDecimal getTotalAmount() {
        return totalAmount;
    }

    public String getStatus() {
        return status;
    }

    public Instant getCreatedAt() {
        return createdAt;
    }

    @Override
    public boolean equals(Object o) {
        if (this == o) return true;
        if (!(o instanceof SyntheticOrder other)) return false;
        return Objects.equals(id, other.id);
    }

    @Override
    public int hashCode() {
        return Objects.hash(id);
    }
}
