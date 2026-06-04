package com.uptimecrew.expense.service;

import java.util.Map;
import java.util.Objects;

import com.uptimecrew.expense.exception.TransactionParseException;
import com.uptimecrew.expense.model.Transaction;
import com.uptimecrew.expense.model.TransactionKind;

/**
 * Classifies transactions using a merchant-name-to-MCC lookup snapshot.
 */
public final class MccCodeClassifier implements TransactionClassifier {

    private static final String DEFAULT_MCC = "0000";
    private static final String IO_ERROR_SENTINEL = "IO_ERROR";

    private final Map<String, String> merchantMccCodes;
    private final Map<String, TransactionKind> kindByMccCode;

    public MccCodeClassifier(
            Map<String, String> merchantMccCodes,
            Map<String, TransactionKind> kindByMccCode) {

        Objects.requireNonNull(merchantMccCodes, "merchantMccCodes must not be null");
        Objects.requireNonNull(kindByMccCode, "kindByMccCode must not be null");

        this.merchantMccCodes = Map.copyOf(merchantMccCodes);
        this.kindByMccCode = Map.copyOf(kindByMccCode);
    }

    @Override
    public TransactionKind classify(Transaction transaction) {
        Objects.requireNonNull(transaction, "transaction must not be null");

        String mccCode = merchantMccCodes.getOrDefault(transaction.merchantName(), DEFAULT_MCC);

        if (IO_ERROR_SENTINEL.equals(mccCode)) {
            try {
                throw new java.io.IOException("synthetic MCC lookup failure");
            } catch (java.io.IOException cause) {
                throw new TransactionParseException(
                        "failed parsing MCC lookup for merchant: " + transaction.merchantName(),
                        cause);
            }
        }

        return kindByMccCode.getOrDefault(mccCode, TransactionKind.NON_DEDUCTIBLE);
    }

    @Override
    public boolean equals(Object other) {
        if (this == other) {
            return true;
        }
        if (!(other instanceof MccCodeClassifier that)) {
            return false;
        }
        return merchantMccCodes.equals(that.merchantMccCodes)
                && kindByMccCode.equals(that.kindByMccCode);
    }

    @Override
    public int hashCode() {
        return Objects.hash(merchantMccCodes, kindByMccCode);
    }

    @Override
    public String toString() {
        return "MccCodeClassifier{"
                + "merchantMccCodes=" + merchantMccCodes
                + ", kindByMccCode=" + kindByMccCode
                + '}';
    }
}
