package com.uptimecrew.expense.embeddings;

import static org.assertj.core.api.Assertions.assertThat;

import java.sql.Connection;
import java.sql.DriverManager;
import java.sql.PreparedStatement;
import java.sql.ResultSet;
import java.sql.Statement;
import java.util.ArrayList;
import java.util.List;
import java.util.UUID;

import org.flywaydb.core.Flyway;
import org.junit.jupiter.api.BeforeAll;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;
import org.testcontainers.containers.PostgreSQLContainer;
import org.testcontainers.junit.jupiter.Container;
import org.testcontainers.junit.jupiter.Testcontainers;
import org.testcontainers.utility.DockerImageName;

/**
 * Testcontainers integration test for the pgvector-backed merchant
 * embeddings table added in V4__create_merchant_embeddings.sql.
 *
 * The container uses the official pgvector image {@code pgvector/pgvector:pg16}
 * and is declared as a compatible substitute for the postgres image so
 * Testcontainers' Postgres wait-strategy applies. {@code withReuse(true)}
 * keeps the container across runs when the developer opts in via
 * {@code testcontainers.reuse.enable=true} in {@code ~/.testcontainers.properties}
 * — CI will not reuse it because the flag is off by default.
 *
 * Vectors used here are deterministic (constants only, no {@link Math#random()},
 * no wallclock-based expected values) so the nearest-neighbor assertion
 * is stable across machines and time zones.
 */
@Testcontainers
class MerchantEmbeddingsRepoIT {

    private static final DockerImageName PGVECTOR_IMAGE =
        DockerImageName.parse("pgvector/pgvector:pg16")
            .asCompatibleSubstituteFor("postgres");

    @Container
    static final PostgreSQLContainer<?> PG =
        new PostgreSQLContainer<>(PGVECTOR_IMAGE)
            .withReuse(true);

    @BeforeAll
    static void applyMigrations() {
        Flyway.configure()
            .dataSource(PG.getJdbcUrl(), PG.getUsername(), PG.getPassword())
            .locations("classpath:db/migration")
            // The pre-existing V3__event_outbox.sql from Week 3 targets
            // the expense schema and doesn't need the vector extension;
            // let Flyway apply it too so version ordering stays clean.
            .baselineOnMigrate(true)
            .load()
            .migrate();
    }

    @BeforeEach
    void truncate() throws Exception {
        try (Connection conn = openConnection();
             Statement stmt = conn.createStatement()) {
            stmt.execute("TRUNCATE expense.merchant_embeddings");
        }
    }

    @Test
    void nearestNeighborFindsMatchingTenantRow() throws Exception {
        // Two orthogonal-ish embedding vectors. Both fill the 1024-D
        // space with a constant so the difference between rows is
        // captured in the first coordinate only, keeping expected
        // ordering easy to reason about without pulling in a linear
        // algebra library.
        float[] axisA = filledVector(1024, 0.01f);
        axisA[0] = 1.0f;

        float[] axisB = filledVector(1024, 0.01f);
        axisB[0] = -1.0f;

        insertRow("tenant-a", axisA);
        insertRow("tenant-a", axisB);
        insertRow("tenant-b", axisA);

        // Probe vector is closer to axisA than to axisB (cosine).
        float[] probe = filledVector(1024, 0.01f);
        probe[0] = 0.95f;

        List<String> nearest = nearestNeighborForTenant("tenant-a", probe, 1);

        assertThat(nearest).hasSize(1);
        assertThat(nearest.get(0)).isEqualTo(vectorLiteral(axisA));
    }

    // --- helpers -------------------------------------------------------

    private static Connection openConnection() throws Exception {
        return DriverManager.getConnection(PG.getJdbcUrl(), PG.getUsername(), PG.getPassword());
    }

    private static float[] filledVector(int dim, float value) {
        float[] v = new float[dim];
        for (int i = 0; i < dim; i++) {
            v[i] = value;
        }
        return v;
    }

    private static String vectorLiteral(float[] v) {
        StringBuilder sb = new StringBuilder(v.length * 8);
        sb.append('[');
        for (int i = 0; i < v.length; i++) {
            if (i > 0) {
                sb.append(',');
            }
            sb.append(v[i]);
        }
        sb.append(']');
        return sb.toString();
    }

    private static void insertRow(String tenant, float[] embedding) throws Exception {
        try (Connection conn = openConnection();
             PreparedStatement ps = conn.prepareStatement(
                 "INSERT INTO expense.merchant_embeddings (id, tenant_id, embedding)"
                 + " VALUES (?, ?, ?::vector)")) {
            ps.setObject(1, UUID.randomUUID());
            ps.setString(2, tenant);
            ps.setString(3, vectorLiteral(embedding));
            ps.executeUpdate();
        }
    }

    private static List<String> nearestNeighborForTenant(String tenant, float[] probe, int limit) throws Exception {
        List<String> out = new ArrayList<>();
        try (Connection conn = openConnection();
             PreparedStatement ps = conn.prepareStatement(
                 "SELECT embedding::text FROM expense.merchant_embeddings"
                 + " WHERE tenant_id = ?"
                 + " ORDER BY embedding <=> ?::vector"
                 + " LIMIT ?")) {
            ps.setString(1, tenant);
            ps.setString(2, vectorLiteral(probe));
            ps.setInt(3, limit);
            try (ResultSet rs = ps.executeQuery()) {
                while (rs.next()) {
                    out.add(rs.getString(1));
                }
            }
        }
        return out;
    }
}
