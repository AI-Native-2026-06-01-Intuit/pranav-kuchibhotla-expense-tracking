package com.uptimecrew.expense;

import static org.assertj.core.api.Assertions.assertThat;

import org.junit.jupiter.api.Test;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.boot.test.context.SpringBootTest;
import org.springframework.test.context.ActiveProfiles;

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
}
