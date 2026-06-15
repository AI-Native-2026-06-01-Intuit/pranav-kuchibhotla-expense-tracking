package com.uptimecrew.expense;

import static org.assertj.core.api.Assertions.assertThat;

import java.math.BigDecimal;
import java.nio.file.Files;
import java.nio.file.Path;
import java.sql.Connection;
import java.sql.DriverManager;
import java.sql.Statement;
import java.time.LocalDate;
import java.util.Optional;

import org.junit.jupiter.api.BeforeAll;
import org.junit.jupiter.api.Test;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.boot.test.context.SpringBootTest;
import org.springframework.boot.testcontainers.service.connection.ServiceConnection;
import org.springframework.cache.Cache;
import org.springframework.cache.CacheManager;
import org.springframework.test.context.ActiveProfiles;
import org.testcontainers.containers.GenericContainer;
import org.testcontainers.containers.MongoDBContainer;
import org.testcontainers.containers.PostgreSQLContainer;
import org.testcontainers.junit.jupiter.Container;
import org.testcontainers.junit.jupiter.Testcontainers;

import com.uptimecrew.expense.model.Transaction;
import com.uptimecrew.expense.readmodel.MerchantReadModel;
import com.uptimecrew.expense.readmodel.MerchantReadModelRepository;
import com.uptimecrew.expense.repository.MerchantRepository;
import com.uptimecrew.expense.service.ExpenseClassificationService;

@Testcontainers
@SpringBootTest
@ActiveProfiles("test")
class MerchantPolyglotIT {

    @Container
    @ServiceConnection
    static final PostgreSQLContainer<?> PG = new PostgreSQLContainer<>("postgres:16-alpine");

    @Container
    @ServiceConnection
    static final MongoDBContainer MONGO = new MongoDBContainer("mongo:7");

    @Container
    @ServiceConnection(name = "redis")
    static final GenericContainer<?> REDIS =
            new GenericContainer<>("redis:7-alpine").withExposedPorts(6379);

    @Autowired
    ExpenseClassificationService service;

    @Autowired
    MerchantRepository merchantRepository;

    @Autowired
    MerchantReadModelRepository readModelRepository;

    @Autowired
    CacheManager cacheManager;

    @BeforeAll
    static void applyPostgresSchema() throws Exception {
        PG.start();
        waitForPostgres();

        String schemaSql = Files.readString(Path.of("db/V1__schema.sql"));
        try (Connection conn = DriverManager.getConnection(
                        PG.getJdbcUrl(), PG.getUsername(), PG.getPassword());
             Statement stmt = conn.createStatement()) {
            stmt.execute(schemaSql);
        }
    }

    @Test
    void write_path_populates_postgres_AND_mongo() {
        Transaction tx = new Transaction(
                "txn-poly-write-001",
                "acct-poly-001",
                new BigDecimal("125.00"),
                "Office Depot Polyglot Write",
                LocalDate.of(2026, 3, 1));
        String expectedId = "merchant-office depot polyglot write";

        service.classify(tx);

        assertThat(merchantRepository.findById(expectedId)).isPresent();
        assertThat(readModelRepository.findById(expectedId)).isPresent();
        assertThat(service.findById(expectedId)).isPresent();
    }

    @Test
    void second_read_is_served_from_redis() {
        Transaction tx = new Transaction(
                "txn-poly-read-001",
                "acct-poly-002",
                new BigDecimal("99.00"),
                "Office Depot Polyglot Read",
                LocalDate.of(2026, 3, 2));
        String id = "merchant-office depot polyglot read";

        service.classify(tx);

        Cache cache = cacheManager.getCache(ExpenseClassificationService.CACHE_NAME);
        assertThat(cache).isNotNull();
        cache.clear();

        Optional<MerchantReadModel> first = service.findById(id);
        assertThat(first).isPresent();

        assertThat(cache.get(id)).isNotNull();

        Optional<MerchantReadModel> second = service.findById(id);
        assertThat(second).isPresent();
    }

    private static void waitForPostgres() throws Exception {
        long deadline = System.currentTimeMillis() + 30_000L;
        Exception lastFailure = null;
        while (System.currentTimeMillis() < deadline) {
            try (Connection conn = DriverManager.getConnection(
                    PG.getJdbcUrl(), PG.getUsername(), PG.getPassword())) {
                return;
            } catch (Exception probeFailure) {
                lastFailure = probeFailure;
                try {
                    Thread.sleep(250L);
                } catch (InterruptedException interrupted) {
                    Thread.currentThread().interrupt();
                    throw interrupted;
                }
            }
        }
        if (lastFailure != null) {
            throw lastFailure;
        }
        throw new IllegalStateException("Postgres did not become reachable within 30s");
    }
}
