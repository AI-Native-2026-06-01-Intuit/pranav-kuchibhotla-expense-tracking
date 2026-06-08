package com.uptimecrew.expense.service;

import java.util.Locale;
import java.util.Objects;

import com.uptimecrew.expense.exception.UnrecognizedMerchantException;
import com.uptimecrew.expense.model.Transaction;
import com.uptimecrew.expense.model.TransactionKind;

/**
 * Classifies transactions using simple merchant-name keyword rules.
 */
public final class MerchantNameClassifier implements TransactionClassifier {

    @Override
    public TransactionKind classify(Transaction transaction) {
        Objects.requireNonNull(transaction, "transaction must not be null");

        String rawMerchantName = transaction.merchantName();
        if (rawMerchantName.trim().isEmpty()) {
            throw new UnrecognizedMerchantException(
                    "unrecognized merchant: '" + rawMerchantName + "'");
        }

        String merchantName = rawMerchantName.toLowerCase(Locale.ROOT);

        if (merchantName.contains("office")
                || merchantName.contains("depot")
                || merchantName.contains("staples")
                || merchantName.contains("adobe")
                || merchantName.contains("github")) {
            return TransactionKind.DEDUCTIBLE;
        }

        return TransactionKind.NON_DEDUCTIBLE;
    }

    @Override
    public boolean equals(Object other) {
        return other instanceof MerchantNameClassifier;
    }

    @Override
    public int hashCode() {
        return MerchantNameClassifier.class.hashCode();
    }

    @Override
    public String toString() {
        return "MerchantNameClassifier{}";
    }
}
