package com.uptimecrew.expense.service;

import com.uptimecrew.expense.model.Transaction;
import com.uptimecrew.expense.model.TransactionKind;

import java.util.Objects;

public final class MerchantNameClassifier implements TransactionClassifier {

    private static final String[] DEDUCTIBLE_KEYWORDS = {"office", "staples", "depot", "uber"};

    @Override
    public TransactionKind classify(Transaction transaction) {
        Objects.requireNonNull(transaction, "transaction");
        String merchant = transaction.merchantName().toLowerCase();
        for (String keyword : DEDUCTIBLE_KEYWORDS) {
            if (merchant.contains(keyword)) {
                return TransactionKind.DEDUCTIBLE;
            }
        }
        return TransactionKind.PERSONAL;
    }
}
