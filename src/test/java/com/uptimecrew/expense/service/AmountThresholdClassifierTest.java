package com.uptimecrew.expense.service;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertThrows;

import java.math.BigDecimal;
import java.time.LocalDate;

import org.junit.jupiter.api.Test;

import com.uptimecrew.expense.model.Transaction;
import com.uptimecrew.expense.model.TransactionKind;

class AmountThresholdClassifierTest {

    @Test
    void classify_amountAtThreshold_returnsDeductible() {
        AmountThresholdClassifier classifier =
                new AmountThresholdClassifier(new BigDecimal("100.00"));

        Transaction transaction = transaction("100.00");

        assertEquals(TransactionKind.DEDUCTIBLE, classifier.classify(transaction));
    }

    @Test
    void classify_amountBelowThreshold_returnsNonDeductible() {
        AmountThresholdClassifier classifier =
                new AmountThresholdClassifier(new BigDecimal("100.00"));

        Transaction transaction = transaction("99.99");

        assertEquals(TransactionKind.NON_DEDUCTIBLE, classifier.classify(transaction));
    }

    @Test
    void constructor_negativeThreshold_throwsIllegalArgumentException() {
        assertThrows(IllegalArgumentException.class,
                () -> new AmountThresholdClassifier(new BigDecimal("-1.00")));
    }

    private static Transaction transaction(String amount) {
        return new Transaction(
                "txn-synth-001",
                "acct-synth-001",
                new BigDecimal(amount),
                "Office Depot",
                LocalDate.of(2026, 3, 1));
    }
}
