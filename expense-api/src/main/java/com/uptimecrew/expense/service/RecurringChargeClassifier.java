package com.uptimecrew.expense.service;

import com.uptimecrew.expense.exception.UnrecognizedMerchantException;
import com.uptimecrew.expense.model.Transaction;
import com.uptimecrew.expense.model.TransactionKind;
import java.time.temporal.ChronoUnit;
import java.util.Comparator;
import java.util.List;
import java.util.Objects;

// Not a Spring @Component: requires a List<Transaction> history with no existing default.
// Construct directly with a caller-supplied history or via a future @Bean factory.
public final class RecurringChargeClassifier implements TransactionClassifier {

    private final List<Transaction> history;

    public RecurringChargeClassifier(List<Transaction> history) {
        Objects.requireNonNull(history, "history must not be null");
        this.history = List.copyOf(history);
    }

    @Override
    public TransactionKind classify(Transaction transaction) {
        Objects.requireNonNull(transaction, "transaction must not be null");
        if (transaction.merchantName().trim().isEmpty()) {
            throw new UnrecognizedMerchantException(
                    "unrecognized merchant: " + transaction.merchantName());
        }

        List<Transaction> matches = history.stream()
                .filter(h -> h.merchantName().equals(transaction.merchantName()))
                .sorted(Comparator.comparing(Transaction::occurredOn))
                .toList();

        if (matches.size() < 2) {
            return TransactionKind.NON_DEDUCTIBLE;
        }

        for (int i = 1; i < matches.size(); i++) {
            long days = ChronoUnit.DAYS.between(
                    matches.get(i - 1).occurredOn(), matches.get(i).occurredOn());
            if (days < 25 || days > 35) {
                return TransactionKind.NON_DEDUCTIBLE;
            }
        }

        for (Transaction match : matches) {
            if (match.amount().compareTo(transaction.amount()) != 0) {
                return TransactionKind.NON_DEDUCTIBLE;
            }
        }

        return TransactionKind.DEDUCTIBLE;
    }
}
