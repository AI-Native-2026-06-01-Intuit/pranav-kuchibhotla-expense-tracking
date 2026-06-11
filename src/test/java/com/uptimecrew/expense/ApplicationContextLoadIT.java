package com.uptimecrew.expense;

import static org.assertj.core.api.Assertions.assertThat;

import java.math.BigDecimal;
import java.time.LocalDate;

import org.junit.jupiter.api.Test;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.boot.test.context.SpringBootTest;
import org.springframework.test.context.ActiveProfiles;

import com.uptimecrew.expense.model.Transaction;
import com.uptimecrew.expense.model.TransactionKind;
import com.uptimecrew.expense.service.ExpenseClassificationService;

@SpringBootTest
@ActiveProfiles("test")
class ApplicationContextLoadIT {

    @Autowired
    ExpenseClassificationService service;

    @Test
    void context_loads_and_service_bean_is_wired() {
        assertThat(service).isNotNull();
    }

    @Test
    void service_delegates_to_primary_strategy() {
        Transaction transaction = new Transaction(
                "txn-synth-001",
                "acct-synth-001",
                new BigDecimal("487.50"),
                "Office Depot",
                LocalDate.of(2026, 3, 1));

        TransactionKind result = service.classify(transaction);

        assertThat(result).isNotNull().isEqualTo(TransactionKind.DEDUCTIBLE);
    }
}
