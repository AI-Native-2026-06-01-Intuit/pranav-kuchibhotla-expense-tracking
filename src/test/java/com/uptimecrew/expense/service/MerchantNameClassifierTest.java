package com.uptimecrew.expense.service;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertNotNull;

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
}
