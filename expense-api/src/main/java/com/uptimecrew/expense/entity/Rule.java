package com.uptimecrew.expense.entity;

import jakarta.persistence.Column;
import jakarta.persistence.Entity;
import jakarta.persistence.Id;
import jakarta.persistence.Table;
import java.math.BigDecimal;
import java.time.Instant;
import java.util.Objects;

/**
 * JPA mapping of the {@code expense.rule} table (W2D1 schema).
 */
@Entity
@Table(schema = "expense", name = "rule")
public class Rule {

    @Id
    @Column(name = "id", length = 64, nullable = false)
    private String id;

    @Column(name = "rule_name", nullable = false)
    private String ruleName;

    @Column(name = "rule_type", nullable = false)
    private String ruleType;

    @Column(name = "pattern", nullable = false)
    private String pattern;

    @Column(name = "minimum_amount", nullable = false)
    private BigDecimal minimumAmount;

    @Column(name = "active", nullable = false)
    private boolean active;

    @Column(name = "created_at", nullable = false, insertable = false, updatable = false)
    private Instant createdAt;

    protected Rule() {
    }

    public Rule(String id,
                String ruleName,
                String ruleType,
                String pattern,
                BigDecimal minimumAmount,
                boolean active) {
        this.id = Objects.requireNonNull(id, "id");
        this.ruleName = Objects.requireNonNull(ruleName, "ruleName");
        this.ruleType = Objects.requireNonNull(ruleType, "ruleType");
        this.pattern = Objects.requireNonNull(pattern, "pattern");
        this.minimumAmount = Objects.requireNonNull(minimumAmount, "minimumAmount");
        this.active = active;
    }

    public String getId() {
        return id;
    }

    public String getRuleName() {
        return ruleName;
    }

    public String getRuleType() {
        return ruleType;
    }

    public String getPattern() {
        return pattern;
    }

    public BigDecimal getMinimumAmount() {
        return minimumAmount;
    }

    public boolean isActive() {
        return active;
    }

    public Instant getCreatedAt() {
        return createdAt;
    }

    @Override
    public boolean equals(Object o) {
        if (this == o) return true;
        if (!(o instanceof Rule other)) return false;
        return Objects.equals(id, other.id);
    }

    @Override
    public int hashCode() {
        return Objects.hash(id);
    }

    @Override
    public String toString() {
        return "Rule{id=" + id + ", ruleName=" + ruleName + ", ruleType=" + ruleType + "}";
    }
}
