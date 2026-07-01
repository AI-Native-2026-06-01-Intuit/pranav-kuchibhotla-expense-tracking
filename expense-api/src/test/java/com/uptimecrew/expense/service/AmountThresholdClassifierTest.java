package com.uptimecrew.expense.service;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertThrows;

import org.junit.jupiter.api.Test;

import com.uptimecrew.expense.model.Transaction;
import com.uptimecrew.expense.model.TransactionKind;
import com.uptimecrew.expense.model.TransactionTestDataBuilder;

import java.math.BigDecimal;

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
        return TransactionTestDataBuilder.aTransaction()
                .withAmount(new BigDecimal(amount))
                .build();
    }
}
