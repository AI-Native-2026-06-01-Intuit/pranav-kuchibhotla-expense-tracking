package com.uptimecrew.expense.entity;

import jakarta.persistence.Column;
import jakarta.persistence.Entity;
import jakarta.persistence.Id;
import jakarta.persistence.Table;
import java.math.BigDecimal;
import java.time.Instant;
import java.util.Objects;

/**
 * JPA mapping of {@code expense.synthetic_refund} (V5 schema).
 *
 * <p>The unique constraint {@code (order_id, idempotency_key)} enforces
 * idempotent refund semantics at the storage layer: attempting to insert
 * a second row for the same (order, key) pair fails, and the service
 * layer looks up the prior row and returns its refund_id unchanged.
 */
@Entity
@Table(schema = "expense", name = "synthetic_refund")
public class SyntheticRefund {

    @Id
    @Column(name = "id", length = 64, nullable = false)
    private String id;

    @Column(name = "order_id", nullable = false)
    private String orderId;

    @Column(name = "tenant_id", nullable = false)
    private String tenantId;

    @Column(name = "amount", nullable = false, precision = 12, scale = 2)
    private BigDecimal amount;

    @Column(name = "reason", nullable = false)
    private String reason;

    @Column(name = "status", nullable = false)
    private String status;

    @Column(name = "idempotency_key", nullable = false)
    private String idempotencyKey;

    @Column(name = "created_at", nullable = false, insertable = false, updatable = false)
    private Instant createdAt;

    protected SyntheticRefund() {
    }

    public SyntheticRefund(String id,
                           String orderId,
                           String tenantId,
                           BigDecimal amount,
                           String reason,
                           String status,
                           String idempotencyKey) {
        this.id = Objects.requireNonNull(id, "id");
        this.orderId = Objects.requireNonNull(orderId, "orderId");
        this.tenantId = Objects.requireNonNull(tenantId, "tenantId");
        this.amount = Objects.requireNonNull(amount, "amount");
        this.reason = Objects.requireNonNull(reason, "reason");
        this.status = Objects.requireNonNull(status, "status");
        this.idempotencyKey = Objects.requireNonNull(idempotencyKey, "idempotencyKey");
    }

    public String getId() {
        return id;
    }

    public String getOrderId() {
        return orderId;
    }

    public String getTenantId() {
        return tenantId;
    }

    public BigDecimal getAmount() {
        return amount;
    }

    public String getReason() {
        return reason;
    }

    public String getStatus() {
        return status;
    }

    public String getIdempotencyKey() {
        return idempotencyKey;
    }

    public Instant getCreatedAt() {
        return createdAt;
    }

    @Override
    public boolean equals(Object o) {
        if (this == o) return true;
        if (!(o instanceof SyntheticRefund other)) return false;
        return Objects.equals(id, other.id);
    }

    @Override
    public int hashCode() {
        return Objects.hash(id);
    }
}
