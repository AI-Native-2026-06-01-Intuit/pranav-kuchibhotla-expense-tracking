package com.uptimecrew.expense.service;

import java.math.BigDecimal;
import java.math.RoundingMode;
import java.util.Objects;

import com.uptimecrew.expense.model.Transaction;
import com.uptimecrew.expense.model.TransactionKind;

/**
 * Classifies transactions as deductible when their amount meets or exceeds a configured threshold.
 */
public final class AmountThresholdClassifier implements TransactionClassifier {

    private final BigDecimal threshold;

    public AmountThresholdClassifier(BigDecimal threshold) {
        Objects.requireNonNull(threshold, "threshold must not be null");
        if (threshold.signum() < 0) {
            throw new IllegalArgumentException("threshold must be >= 0");
        }
        this.threshold = threshold.setScale(2, RoundingMode.HALF_UP);
    }

    @Override
    public TransactionKind classify(Transaction transaction) {
        Objects.requireNonNull(transaction, "transaction must not be null");

        if (transaction.amount().compareTo(threshold) >= 0) {
            return TransactionKind.DEDUCTIBLE;
        }

        return TransactionKind.NON_DEDUCTIBLE;
    }

    public BigDecimal threshold() {
        return threshold;
    }

    @Override
    public boolean equals(Object other) {
        if (this == other) {
            return true;
        }
        if (!(other instanceof AmountThresholdClassifier that)) {
            return false;
        }
        return threshold.equals(that.threshold);
    }

    @Override
    public int hashCode() {
        return Objects.hash(threshold);
    }

    @Override
    public String toString() {
        return "AmountThresholdClassifier{"
                + "threshold=" + threshold
                + '}';
    }
}
