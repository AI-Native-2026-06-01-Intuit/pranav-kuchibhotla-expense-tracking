package com.uptimecrew.expense.service;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertTrue;

import java.math.BigDecimal;
import java.time.LocalDate;
import java.util.ArrayList;
import java.util.List;

import org.junit.jupiter.api.Test;

import com.uptimecrew.expense.model.Transaction;

class TransactionLedgerTest {

    @Test
    void constructor_mutatedSourceCollection_keepsDefensiveSnapshot() {
        List<Transaction> source = new ArrayList<>();
        source.add(transaction("txn-001", "Office Depot", "487.50", LocalDate.of(2026, 3, 1)));

        TransactionLedger ledger = new TransactionLedger(source);

        source.add(transaction("txn-002", "Office Depot", "999.00", LocalDate.of(2026, 3, 2)));

        assertEquals(1, ledger.size());
        assertTrue(ledger.findById("txn-002").isEmpty());
    }

    @Test
    void findById_existingId_returnsTransactionOptional() {
        Transaction expected = transaction("txn-001", "Office Depot", "487.50", LocalDate.of(2026, 3, 1));
        TransactionLedger ledger = new TransactionLedger(List.of(expected));

        Transaction actual = ledger.findById("txn-001")
                .orElseThrow(() -> new AssertionError("expected transaction"));

        assertEquals(expected, actual);
    }

    @Test
    void findById_missingId_returnsEmptyOptional() {
        TransactionLedger ledger = new TransactionLedger(List.of(
                transaction("txn-001", "Office Depot", "487.50", LocalDate.of(2026, 3, 1))
        ));

        assertTrue(ledger.findById("txn-missing").isEmpty());
    }

    @Test
    void findByMerchantAbove_matchingTransactions_returnsSortedNewestFirst() {
        Transaction olderMatch = transaction("txn-001", "Office Depot", "487.50", LocalDate.of(2026, 3, 1));
        Transaction belowThreshold = transaction("txn-002", "Office Depot", "10.00", LocalDate.of(2026, 3, 3));
        Transaction otherMerchant = transaction("txn-003", "Coffee Shop", "999.00", LocalDate.of(2026, 3, 4));
        Transaction newerMatch = transaction("txn-004", "Office Depot", "600.00", LocalDate.of(2026, 3, 5));

        TransactionLedger ledger = new TransactionLedger(List.of(
                olderMatch,
                belowThreshold,
                otherMerchant,
                newerMatch
        ));

        List<Transaction> results = ledger.findByMerchantAbove("office", new BigDecimal("100.00"));

        assertEquals(List.of(newerMatch, olderMatch), results);
    }

    private static Transaction transaction(
            String id,
            String merchantName,
            String amount,
            LocalDate occurredOn) {

        return new Transaction(
                id,
                "acct-synth-001",
                new BigDecimal(amount),
                merchantName,
                occurredOn);
    }
}
