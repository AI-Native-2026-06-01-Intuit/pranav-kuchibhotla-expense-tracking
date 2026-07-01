package com.uptimecrew.expense.repository;

import static org.assertj.core.api.Assertions.assertThat;

import java.nio.file.Files;
import java.nio.file.Path;
import java.sql.Connection;
import java.sql.DriverManager;
import java.sql.Statement;
import java.util.Optional;

import org.junit.jupiter.api.BeforeAll;
import org.junit.jupiter.api.Test;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.boot.test.autoconfigure.jdbc.AutoConfigureTestDatabase;
import org.springframework.boot.test.autoconfigure.orm.jpa.DataJpaTest;
import org.springframework.boot.testcontainers.service.connection.ServiceConnection;
import org.springframework.test.context.TestPropertySource;
import org.testcontainers.containers.PostgreSQLContainer;
import org.testcontainers.junit.jupiter.Container;
import org.testcontainers.junit.jupiter.Testcontainers;

import com.uptimecrew.expense.entity.Merchant;

/**
 * Integration test for {@link MerchantRepository}, backed by a real
 * Postgres container via Testcontainers + Spring Boot {@code @ServiceConnection}.
 *
 * <p>{@code ddl-auto} is forced to {@code none} for this test because
 * {@code @DataJpaTest} builds the EntityManagerFactory <em>before</em>
 * {@code @BeforeAll} runs the schema, so Hibernate's startup validation
 * would otherwise fail against an empty database.
 */
@Testcontainers
@DataJpaTest
@AutoConfigureTestDatabase(replace = AutoConfigureTestDatabase.Replace.NONE)
@TestPropertySource(properties = "spring.jpa.hibernate.ddl-auto=none")
class MerchantRepositoryIT {

    @Container
    @ServiceConnection
    static final PostgreSQLContainer<?> PG = new PostgreSQLContainer<>("postgres:16-alpine");

    @Autowired
    private MerchantRepository merchantRepository;

    @BeforeAll
    static void applySchema() throws Exception {
        // Rancher Desktop with the overridden socket sometimes returns from
        // the container's readiness wait before Postgres accepts JDBC, so
        // start explicitly and poll until a connection is accepted.
        PG.start();
        waitForPostgres();

        String schemaSql = Files.readString(Path.of("db/V1__schema.sql"));
        try (Connection conn = openConnection();
             Statement stmt = conn.createStatement()) {
            stmt.execute(schemaSql);
        }
    }

    @Test
    void save_and_find_round_trip() {
        Merchant merchant = new Merchant(
                "merchant-it-roundtrip-001",
                "Office Depot",
                "office-depot-roundtrip",
                "BUSINESS");

        merchantRepository.save(merchant);
        merchantRepository.flush();

        Optional<Merchant> found = merchantRepository.findById("merchant-it-roundtrip-001");
        assertThat(found).isPresent();
        assertThat(found.get().getDisplayName()).isEqualTo("Office Depot");
        assertThat(found.get().getNormalizedName()).isEqualTo("office-depot-roundtrip");
        assertThat(found.get().getMerchantKind()).isEqualTo("BUSINESS");
    }

    @Test
    void derived_finder_returns_only_matching_rows() {
        Merchant matching = new Merchant(
                "merchant-it-derived-match",
                "Office Depot",
                "office-depot-derived",
                "BUSINESS");
        Merchant other = new Merchant(
                "merchant-it-derived-other",
                "Starbucks",
                "starbucks-derived",
                "PERSONAL");

        merchantRepository.save(matching);
        merchantRepository.save(other);
        merchantRepository.flush();

        Optional<Merchant> result = merchantRepository.findByNormalizedName("office-depot-derived");
        assertThat(result)
                .isPresent()
                .get()
                .extracting(Merchant::getId)
                .isEqualTo("merchant-it-derived-match");

        Optional<Merchant> miss = merchantRepository.findByNormalizedName("does-not-exist");
        assertThat(miss).isEmpty();
    }

    private static Connection openConnection() throws Exception {
        return DriverManager.getConnection(
                PG.getJdbcUrl(),
                PG.getUsername(),
                PG.getPassword());
    }

    private static void waitForPostgres() throws Exception {
        long deadline = System.currentTimeMillis() + 30_000L;
        Exception lastFailure = null;
        while (System.currentTimeMillis() < deadline) {
            try (Connection conn = openConnection()) {
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
