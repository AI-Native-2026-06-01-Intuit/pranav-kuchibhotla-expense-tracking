package com.uptimecrew.expense.model;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertThrows;

import java.math.BigDecimal;
import java.time.LocalDate;

import org.junit.jupiter.api.Test;

class TransactionTest {

    @Test
    void constructor_validInputs_setsFields() {
        Transaction subject = new Transaction(
                "txn-synth-001",
                "acct-synth-001",
                new BigDecimal("487.50"),
                "Office Depot",
                LocalDate.of(2026, 3, 1));

        assertEquals("txn-synth-001", subject.id());
        assertEquals("acct-synth-001", subject.accountId());
        assertEquals(0, new BigDecimal("487.50").compareTo(subject.amount()));
        assertEquals("Office Depot", subject.merchantName());
        assertEquals(LocalDate.of(2026, 3, 1), subject.occurredOn());
    }

    @Test
    void constructor_nullId_throwsNullPointerException() {
        assertThrows(NullPointerException.class, () -> new Transaction(
                null,
                "acct-synth-001",
                new BigDecimal("487.50"),
                "Office Depot",
                LocalDate.of(2026, 3, 1)));
    }

    @Test
    void constructor_negativeAmount_throwsIllegalArgumentException() {
        assertThrows(IllegalArgumentException.class, () -> new Transaction(
                "txn-synth-001",
                "acct-synth-001",
                new BigDecimal("-1.00"),
                "Office Depot",
                LocalDate.of(2026, 3, 1)));
    }
}
