package com.uptimecrew.expense.service;

import java.util.Objects;

import com.uptimecrew.expense.model.Transaction;
import com.uptimecrew.expense.model.TransactionKind;

/**
 * Service that classifies expenses by delegating to an injected transaction classifier.
 */
public final class ExpenseClassificationService {

    private final TransactionClassifier classifier;

    public ExpenseClassificationService(TransactionClassifier classifier) {
        this.classifier = Objects.requireNonNull(classifier, "classifier must not be null");
    }

    public TransactionKind classify(Transaction transaction) {
        Objects.requireNonNull(transaction, "transaction must not be null");
        return classifier.classify(transaction);
    }
}
