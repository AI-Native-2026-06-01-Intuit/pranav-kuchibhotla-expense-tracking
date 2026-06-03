package com.uptimecrew.expense.model;

/**
 * Whether a {@link Transaction} is tax-deductible. Produced by a
 * {@link com.uptimecrew.expense.service.TransactionClassifier}.
 */
public enum TransactionKind {
    DEDUCTIBLE,
    NON_DEDUCTIBLE
}
