package com.uptimecrew.expense.service;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertNotNull;
import static org.junit.jupiter.api.Assertions.assertThrows;

import java.math.BigDecimal;
import java.time.LocalDate;

import org.junit.jupiter.api.Test;

import com.uptimecrew.expense.model.Transaction;
import com.uptimecrew.expense.model.TransactionKind;

class MerchantNameClassifierTest {

    @Test
    void classify_officeMerchant_returnsDeductible() {
        TransactionClassifier classifier = new MerchantNameClassifier();

        Transaction transaction = new Transaction(
                "txn-synth-001",
                "acct-synth-001",
                new BigDecimal("487.50"),
                "Office Depot",
                LocalDate.of(2026, 3, 1));

        TransactionKind result = classifier.classify(transaction);

        assertNotNull(result);
        assertEquals(TransactionKind.DEDUCTIBLE, result);
    }

    @Test
    void classify_groceryMerchant_returnsNonDeductible() {
        TransactionClassifier classifier = new MerchantNameClassifier();

        Transaction transaction = new Transaction(
                "txn-synth-002",
                "acct-synth-001",
                new BigDecimal("42.10"),
                "Neighborhood Grocery",
                LocalDate.of(2026, 3, 2));

        TransactionKind result = classifier.classify(transaction);

        assertNotNull(result);
        assertEquals(TransactionKind.NON_DEDUCTIBLE, result);
    }

    @Test
    void classify_nullTransaction_throwsNullPointerException() {
        TransactionClassifier classifier = new MerchantNameClassifier();

        assertThrows(NullPointerException.class, () -> classifier.classify(null));
    }
}
