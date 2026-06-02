package com.uptimecrew.expense.model;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertThrows;

import java.math.BigDecimal;

import org.junit.jupiter.api.Test;

class ExpenseCategoryTest {

    @Test
    void constructor_validInputs_setsFields() {
        ExpenseCategory subject = new ExpenseCategory(
                "cat-synth-001",
                "Office Supplies",
                new BigDecimal("100.00"));

        assertEquals("cat-synth-001", subject.id());
        assertEquals("Office Supplies", subject.name());
        assertEquals(0, new BigDecimal("100.00").compareTo(subject.deductiblePercent()));
    }

    @Test
    void constructor_nullName_throwsNullPointerException() {
        assertThrows(NullPointerException.class, () -> new ExpenseCategory(
                "cat-synth-001",
                null,
                new BigDecimal("100.00")));
    }

    @Test
    void constructor_blankName_throwsIllegalArgumentException() {
        assertThrows(IllegalArgumentException.class, () -> new ExpenseCategory(
                "cat-synth-001",
                "",
                new BigDecimal("100.00")));
    }
}
