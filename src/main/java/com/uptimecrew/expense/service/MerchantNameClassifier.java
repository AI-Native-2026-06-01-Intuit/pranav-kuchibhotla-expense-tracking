package com.uptimecrew.expense.service;

import java.util.Locale;
import java.util.Objects;

import com.uptimecrew.expense.model.Transaction;
import com.uptimecrew.expense.model.TransactionKind;

/**
 * A {@link TransactionClassifier} that infers {@link TransactionKind} from
 * the transaction's merchant name using a small keyword list.
 */
public final class MerchantNameClassifier implements TransactionClassifier {

    @Override
    public TransactionKind classify(Transaction transaction) {
        Objects.requireNonNull(transaction, "transaction must not be null");

        String merchantName = transaction.merchantName().toLowerCase(Locale.ROOT);

        if (merchantName.contains("office")
                || merchantName.contains("depot")
                || merchantName.contains("staples")
                || merchantName.contains("adobe")
                || merchantName.contains("github")) {
            return TransactionKind.DEDUCTIBLE;
        }

        return TransactionKind.NON_DEDUCTIBLE;
    }
}
