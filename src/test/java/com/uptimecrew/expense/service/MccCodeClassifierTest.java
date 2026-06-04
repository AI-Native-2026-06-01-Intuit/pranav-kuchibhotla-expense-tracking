package com.uptimecrew.expense.service;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertThrows;

import java.math.BigDecimal;
import java.time.LocalDate;
import java.util.Map;

import org.junit.jupiter.api.Test;

import com.uptimecrew.expense.model.Transaction;
import com.uptimecrew.expense.model.TransactionKind;

class MccCodeClassifierTest {

    @Test
    void classify_knownDeductibleMcc_returnsDeductible() {
        MccCodeClassifier classifier = new MccCodeClassifier(
                Map.of("Office Depot", "5943"),
                Map.of("5943", TransactionKind.DEDUCTIBLE));

        Transaction transaction = transaction("Office Depot");

        assertEquals(TransactionKind.DEDUCTIBLE, classifier.classify(transaction));
    }

    @Test
    void classify_unknownMerchant_returnsNonDeductible() {
        MccCodeClassifier classifier = new MccCodeClassifier(
                Map.of("Office Depot", "5943"),
                Map.of("5943", TransactionKind.DEDUCTIBLE));

        Transaction transaction = transaction("Coffee Shop");

        assertEquals(TransactionKind.NON_DEDUCTIBLE, classifier.classify(transaction));
    }

    @Test
    void constructor_nullMerchantMap_throwsNullPointerException() {
        assertThrows(NullPointerException.class,
                () -> new MccCodeClassifier(null, Map.of("5943", TransactionKind.DEDUCTIBLE)));
    }

    private static Transaction transaction(String merchantName) {
        return new Transaction(
                "txn-synth-001",
                "acct-synth-001",
                new BigDecimal("487.50"),
                merchantName,
                LocalDate.of(2026, 3, 1));
    }
}
