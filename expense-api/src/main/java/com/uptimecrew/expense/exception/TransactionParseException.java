package com.uptimecrew.expense.exception;

/**
 * Thrown when a transaction payload cannot be parsed into the domain model —
 * for example, due to malformed input, missing required fields, or invalid
 * field values encountered during classification.
 */
public final class TransactionParseException extends ExpenseClassificationException {

    public TransactionParseException(String message) {
        super(message);
    }

    public TransactionParseException(String message, Throwable cause) {
        super(message, cause);
    }
}
