package com.uptimecrew.expense.service;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertNotNull;

import java.math.BigDecimal;
import java.util.Map;

import org.junit.jupiter.api.Test;

import com.uptimecrew.expense.model.TransactionKind;

class TransactionClassifiersTest {

    @Test
    void byMerchantName_returnsEquivalentClassifiers() {
        TransactionClassifier first = TransactionClassifiers.byMerchantName();
        TransactionClassifier second = TransactionClassifiers.byMerchantName();

        assertNotNull(first);
        assertEquals(first, second);
    }

    @Test
    void byAmountThreshold_returnsEquivalentClassifiers() {
        TransactionClassifier first = TransactionClassifiers.byAmountThreshold(new BigDecimal("100.00"));
        TransactionClassifier second = TransactionClassifiers.byAmountThreshold(new BigDecimal("100.00"));

        assertNotNull(first);
        assertEquals(first, second);
    }

    @Test
    void byMccLookup_returnsEquivalentClassifiers() {
        Map<String, String> merchantMccCodes = Map.of("Office Depot", "5943");
        Map<String, TransactionKind> kindByMccCode = Map.of("5943", TransactionKind.DEDUCTIBLE);

        TransactionClassifier first = TransactionClassifiers.byMccLookup(merchantMccCodes, kindByMccCode);
        TransactionClassifier second = TransactionClassifiers.byMccLookup(merchantMccCodes, kindByMccCode);

        assertNotNull(first);
        assertEquals(first, second);
    }
}
