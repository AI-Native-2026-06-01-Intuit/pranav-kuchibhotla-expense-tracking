package com.uptimecrew.expense.service;

import java.math.BigDecimal;
import java.util.Collection;
import java.util.Comparator;
import java.util.Map;
import java.util.Objects;
import java.util.Optional;
import java.util.function.Function;
import java.util.stream.Collectors;
import java.util.List;

import com.uptimecrew.expense.model.Transaction;

/**
 * Immutable ledger of transactions keyed by transaction id.
 */
public final class TransactionLedger {

    private final Map<String, Transaction> transactionsById;

    public TransactionLedger(Collection<Transaction> transactions) {
        Objects.requireNonNull(transactions, "transactions must not be null");

        this.transactionsById = Map.copyOf(transactions.stream()
                .collect(Collectors.toMap(
                        Transaction::id,
                        Function.identity())));
    }

    public int size() {
        return transactionsById.size();
    }

    public Optional<Transaction> findById(String id) {
        Objects.requireNonNull(id, "id must not be null");
        return Optional.ofNullable(transactionsById.get(id));
    }

    public List<Transaction> findByMerchantAbove(String merchantFragment, BigDecimal threshold) {
        Objects.requireNonNull(merchantFragment, "merchantFragment must not be null");
        Objects.requireNonNull(threshold, "threshold must not be null");

        String normalizedFragment = merchantFragment.toLowerCase();

        return transactionsById.values().stream()
                .filter(transaction -> transaction.merchantName().toLowerCase().contains(normalizedFragment))
                .filter(transaction -> transaction.amount().compareTo(threshold) > 0)
                .sorted(Comparator
                        .comparing(Transaction::occurredOn)
                        .reversed()
                        .thenComparing(Transaction::id))
                .toList();
    }
}
