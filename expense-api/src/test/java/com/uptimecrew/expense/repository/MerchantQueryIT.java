package com.uptimecrew.expense.repository;

import org.junit.jupiter.api.BeforeAll;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.TestInstance;
import org.testcontainers.containers.PostgreSQLContainer;
import org.testcontainers.junit.jupiter.Container;
import org.testcontainers.junit.jupiter.Testcontainers;

import java.math.BigDecimal;
import java.nio.file.Files;
import java.nio.file.Path;
import java.sql.Connection;
import java.sql.DriverManager;
import java.sql.ResultSet;
import java.sql.Statement;
import java.util.ArrayList;
import java.util.List;

import static org.assertj.core.api.Assertions.assertThat;

@Testcontainers
@TestInstance(TestInstance.Lifecycle.PER_CLASS)
class MerchantQueryIT {

    @Container
    static final PostgreSQLContainer<?> POSTGRES =
            new PostgreSQLContainer<>("postgres:16-alpine");

    @BeforeAll
    void applySchemaAndSeed() throws Exception {
        // Some Docker setups (Rancher Desktop with overridden socket) race
        // ahead of the @Container readiness wait, so start explicitly and
        // then poll JDBC until the server actually accepts connections.
        POSTGRES.start();
        waitForPostgres();
        String schemaSql = Files.readString(Path.of("db/V1__schema.sql"));
        String seedFile  = Files.readString(Path.of("db/V2__seed.sql"));

        // V2__seed.sql ends the main seed at the first COMMIT and then contains
        // an intentional CHECK-constraint failure wrapped in its own BEGIN/ROLLBACK.
        // JDBC would surface that failure and abort setup, so apply only the
        // main block: everything up to and including the first COMMIT.
        int firstCommitEnd = seedFile.indexOf("COMMIT;");
        if (firstCommitEnd < 0) {
            throw new IllegalStateException("Expected COMMIT; in db/V2__seed.sql");
        }
        String mainSeed = seedFile.substring(0, firstCommitEnd + "COMMIT;".length());

        try (Connection conn = openConnection();
             Statement stmt = conn.createStatement()) {
            stmt.execute(schemaSql);
            stmt.execute(mainSeed);
        }
    }

    @Test
    void cteQuery_seededData_returnsMerchantsAtOrAboveThreshold() throws Exception {
        String sql = Files.readString(Path.of("db/queries/cte.sql"));

        List<String> merchantIds = new ArrayList<>();
        List<BigDecimal> totals = new ArrayList<>();

        try (Connection conn = openConnection();
             Statement stmt = conn.createStatement();
             ResultSet rs = executeQueryFile(stmt, sql)) {
            while (rs.next()) {
                merchantIds.add(rs.getString("merchant_id"));
                totals.add(rs.getBigDecimal("total_amount"));
            }
        }

        assertThat(merchantIds).isNotEmpty();
        assertThat(merchantIds).contains(
                "merch-2026-0001",
                "merch-2026-0002",
                "merch-2026-0004");
        assertThat(totals).allMatch(t -> t.compareTo(new BigDecimal("50.00")) >= 0);
    }

    @Test
    void windowQuery_seededData_returnsRanksAndMerchantTotals() throws Exception {
        String sql = Files.readString(Path.of("db/queries/window.sql"));

        record WindowRow(
                String transactionId,
                String merchantId,
                long amountRank,
                BigDecimal merchantTotal) {}

        List<WindowRow> rows = new ArrayList<>();

        try (Connection conn = openConnection();
             Statement stmt = conn.createStatement();
             ResultSet rs = executeQueryFile(stmt, sql)) {
            while (rs.next()) {
                rows.add(new WindowRow(
                        rs.getString("transaction_id"),
                        rs.getString("merchant_id"),
                        rs.getLong("amount_rank"),
                        rs.getBigDecimal("merchant_total")));
            }
        }

        assertThat(rows).isNotEmpty();
        assertThat(rows).extracting(WindowRow::transactionId).contains("txn-2026-0001");

        List<WindowRow> merch1Rows = rows.stream()
                .filter(r -> "merch-2026-0001".equals(r.merchantId()))
                .toList();
        assertThat(merch1Rows).hasSize(2);
        assertThat(merch1Rows)
                .extracting(WindowRow::merchantTotal)
                .allSatisfy(total ->
                        assertThat(total).isEqualByComparingTo(new BigDecimal("50.25")));
    }

    private static Connection openConnection() throws Exception {
        return DriverManager.getConnection(
                POSTGRES.getJdbcUrl(),
                POSTGRES.getUsername(),
                POSTGRES.getPassword());
    }

    private static void waitForPostgres() throws Exception {
        long deadline = System.currentTimeMillis() + 30_000L;
        Exception lastFailure = null;
        while (System.currentTimeMillis() < deadline) {
            try (Connection conn = openConnection()) {
                // Connection acquired -> Postgres is accepting TCP and auth.
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

    // Query files start with a SET statement that returns no ResultSet, then
    // a SELECT. Statement.execute() returns true when a ResultSet is current;
    // when false, getUpdateCount() == -1 signals no more results. We advance
    // until a ResultSet appears (or the results are exhausted).
    private static ResultSet executeQueryFile(Statement stmt, String sql) throws Exception {
        boolean hasResultSet = stmt.execute(sql);
        while (!hasResultSet && stmt.getUpdateCount() != -1) {
            hasResultSet = stmt.getMoreResults();
        }
        if (!hasResultSet) {
            throw new IllegalStateException("SQL file did not produce a ResultSet");
        }
        return stmt.getResultSet();
    }
}
