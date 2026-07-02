package com.uptimecrew.expense.exception;

/**
 * Base type for failures raised while classifying an expense transaction.
 *
 * <p>Concrete subclasses describe specific failure modes (e.g., an unknown
 * merchant or a malformed transaction payload). Callers can catch this type
 * to handle any classification error uniformly.
 */
public abstract class ExpenseClassificationException extends RuntimeException {

    protected ExpenseClassificationException(String message) {
        super(message);
    }

    protected ExpenseClassificationException(String message, Throwable cause) {
        super(message, cause);
    }
}
