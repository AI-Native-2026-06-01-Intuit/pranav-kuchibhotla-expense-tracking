package com.uptimecrew.expense.service;

import java.util.Objects;

import org.slf4j.Logger;
import org.slf4j.LoggerFactory;

import com.uptimecrew.expense.exception.ExpenseClassificationException;
import com.uptimecrew.expense.model.Transaction;
import com.uptimecrew.expense.model.TransactionKind;

/**
 * Service that classifies expenses by delegating to an injected transaction classifier.
 */
public final class ExpenseClassificationService {

    private static final Logger LOG = LoggerFactory.getLogger(ExpenseClassificationService.class);

    private final TransactionClassifier classifier;

    public ExpenseClassificationService(TransactionClassifier classifier) {
        this.classifier = Objects.requireNonNull(classifier, "classifier must not be null");
    }

    public TransactionKind classify(Transaction transaction) {
        Objects.requireNonNull(transaction, "transaction must not be null");

        LOG.info("classifying transaction id={} merchant={}",
                transaction.id(), transaction.merchantName());
        try {
            TransactionKind kind = classifier.classify(transaction);
            LOG.info("classified transaction id={} as kind={}", transaction.id(), kind);
            return kind;
        } catch (ExpenseClassificationException ex) {
            LOG.warn("strategy failed: {}", ex.getMessage(), ex);
            throw ex;
        }
    }
}
