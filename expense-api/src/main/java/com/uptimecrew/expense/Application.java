package com.uptimecrew.expense;

import org.springframework.boot.SpringApplication;
import org.springframework.boot.autoconfigure.SpringBootApplication;
import org.springframework.cache.annotation.EnableCaching;
import org.springframework.cloud.openfeign.EnableFeignClients;
import org.springframework.scheduling.annotation.EnableScheduling;

/**
 * Spring Boot entry point for the expense-tracking application.
 * <p>
 * {@link SpringBootApplication} enables component scanning over the
 * {@code com.uptimecrew.expense} package and its subpackages, so any
 * stereotype-annotated classes (added later) will be picked up automatically.
 */
@SpringBootApplication
@EnableCaching
@EnableFeignClients
@EnableScheduling
public final class Application {

    public static void main(String[] args) {
        SpringApplication.run(Application.class, args);
    }
}
