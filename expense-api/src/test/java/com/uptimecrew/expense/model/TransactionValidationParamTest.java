package com.uptimecrew.expense.model;

import static org.junit.jupiter.api.Assertions.assertThrows;

import java.math.BigDecimal;
import java.time.LocalDate;

import org.junit.jupiter.params.ParameterizedTest;
import org.junit.jupiter.params.provider.CsvSource;

class TransactionValidationParamTest {

    @ParameterizedTest(name = "rejects blank id value: [{0}]")
    @CsvSource({
            "' '",
            "'   '",
            "'\t'"
    })
    void constructor_blankId_throwsIllegalArgumentException(String id) {
        assertThrows(IllegalArgumentException.class, () -> new Transaction(
                id,
                "acct-synth-001",
                new BigDecimal("487.50"),
                "Office Depot",
                LocalDate.of(2026, 3, 1)));
    }
}
