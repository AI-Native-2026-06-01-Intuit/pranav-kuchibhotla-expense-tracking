package com.uptimecrew.expense.service;

import com.uptimecrew.expense.model.Transaction;
import com.uptimecrew.expense.model.TransactionKind;

/**
 * Assigns a {@link TransactionKind} to a {@link Transaction}. Implementations
 * decide the classification strategy (e.g., by merchant name).
 */
public interface TransactionClassifier {

    TransactionKind classify(Transaction transaction);
}
