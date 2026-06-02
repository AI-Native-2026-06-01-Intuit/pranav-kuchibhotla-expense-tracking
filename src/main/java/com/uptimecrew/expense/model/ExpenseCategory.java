package com.uptimecrew.expense.model;

import java.math.BigDecimal;
import java.math.RoundingMode;
import java.util.Objects;

public final class ExpenseCategory {

    private final String id;
    private final String name;
    private final BigDecimal deductiblePercent;

    public ExpenseCategory(String id, String name, BigDecimal deductiblePercent) {
        Objects.requireNonNull(id, "id");
        Objects.requireNonNull(name, "name");
        Objects.requireNonNull(deductiblePercent, "deductiblePercent");
        if (id.isBlank()) {
            throw new IllegalArgumentException("id must not be blank");
        }
        if (name.isBlank()) {
            throw new IllegalArgumentException("name must not be blank");
        }
        if (deductiblePercent.signum() < 0) {
            throw new IllegalArgumentException("deductiblePercent must not be negative");
        }
        this.id = id;
        this.name = name;
        this.deductiblePercent = deductiblePercent.setScale(2, RoundingMode.HALF_UP);
    }

    public String id() {
        return id;
    }

    public String name() {
        return name;
    }

    public BigDecimal deductiblePercent() {
        return deductiblePercent;
    }

    @Override
    public boolean equals(Object o) {
        if (this == o) return true;
        if (!(o instanceof ExpenseCategory other)) return false;
        return id.equals(other.id)
                && name.equals(other.name)
                && deductiblePercent.equals(other.deductiblePercent);
    }

    @Override
    public int hashCode() {
        return Objects.hash(id, name, deductiblePercent);
    }

    @Override
    public String toString() {
        return "ExpenseCategory{id=" + id
                + ", name=" + name
                + ", deductiblePercent=" + deductiblePercent
                + '}';
    }
}
