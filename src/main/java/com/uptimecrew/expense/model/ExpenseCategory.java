package com.uptimecrew.expense.model;

import java.math.BigDecimal;
import java.math.RoundingMode;
import java.util.Objects;

/**
 * A category that may be assigned to a {@link Transaction}, along with the
 * percentage of the transaction amount that is tax-deductible (0–100).
 */
public final class ExpenseCategory {

    private final String id;
    private final String name;
    private final BigDecimal deductiblePercent;

    public ExpenseCategory(String id, String name, BigDecimal deductiblePercent) {
        this.id = requireNonBlank(id, "id");
        this.name = requireNonBlank(name, "name");
        this.deductiblePercent = normalizePercent(deductiblePercent);
    }

    private static String requireNonBlank(String value, String fieldName) {
        Objects.requireNonNull(value, fieldName + " must not be null");
        if (value.isBlank()) {
            throw new IllegalArgumentException(fieldName + " must be non-blank");
        }
        return value;
    }

    private static BigDecimal normalizePercent(BigDecimal value) {
        Objects.requireNonNull(value, "deductiblePercent must not be null");
        if (value.signum() < 0 || value.compareTo(new BigDecimal("100.00")) > 0) {
            throw new IllegalArgumentException("deductiblePercent must be between 0 and 100");
        }
        return value.setScale(2, RoundingMode.HALF_UP);
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
    public boolean equals(Object other) {
        if (this == other) {
            return true;
        }
        if (!(other instanceof ExpenseCategory that)) {
            return false;
        }
        return id.equals(that.id)
                && name.equals(that.name)
                && deductiblePercent.equals(that.deductiblePercent);
    }

    @Override
    public int hashCode() {
        return Objects.hash(id, name, deductiblePercent);
    }

    @Override
    public String toString() {
        return "ExpenseCategory{"
                + "id='" + id + '\''
                + ", name='" + name + '\''
                + ", deductiblePercent=" + deductiblePercent
                + '}';
    }
}
