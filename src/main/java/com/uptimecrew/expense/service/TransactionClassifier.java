package com.uptimecrew.expense.service;

import com.uptimecrew.expense.model.Transaction;
import com.uptimecrew.expense.model.TransactionKind;

public interface TransactionClassifier {

    TransactionKind classify(Transaction transaction);
}
