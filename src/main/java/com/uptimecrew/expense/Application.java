package com.uptimecrew.expense;

import org.springframework.boot.SpringApplication;
import org.springframework.boot.autoconfigure.SpringBootApplication;

/**
 * Spring Boot entry point for the expense-tracking application.
 * <p>
 * {@link SpringBootApplication} enables component scanning over the
 * {@code com.uptimecrew.expense} package and its subpackages, so any
 * stereotype-annotated classes (added later) will be picked up automatically.
 */
@SpringBootApplication
public final class Application {

    public static void main(String[] args) {
        SpringApplication.run(Application.class, args);
    }
}
