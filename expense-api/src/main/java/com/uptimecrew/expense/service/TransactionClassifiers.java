package com.uptimecrew.expense.service;

import java.math.BigDecimal;
import java.util.Map;

import com.uptimecrew.expense.model.TransactionKind;

/**
 * Factory methods for supported transaction classification strategies.
 */
public final class TransactionClassifiers {

    private TransactionClassifiers() {
        throw new AssertionError("TransactionClassifiers is a factory and must not be instantiated");
    }

    public static TransactionClassifier byMerchantName() {
        return new MerchantNameClassifier();
    }

    public static TransactionClassifier byAmountThreshold(BigDecimal threshold) {
        return new AmountThresholdClassifier(threshold);
    }

    public static TransactionClassifier byMccLookup(
            Map<String, String> merchantMccCodes,
            Map<String, TransactionKind> kindByMccCode) {

        return new MccCodeClassifier(merchantMccCodes, kindByMccCode);
    }
}
