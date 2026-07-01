package com.uptimecrew.expense.exception;

/**
 * Thrown when a classifier cannot map a transaction's merchant to a known
 * category — typically because the merchant name or MCC is absent from the
 * classifier's lookup data.
 */
public final class UnrecognizedMerchantException extends ExpenseClassificationException {

    public UnrecognizedMerchantException(String message) {
        super(message);
    }

    public UnrecognizedMerchantException(String message, Throwable cause) {
        super(message, cause);
    }
}
