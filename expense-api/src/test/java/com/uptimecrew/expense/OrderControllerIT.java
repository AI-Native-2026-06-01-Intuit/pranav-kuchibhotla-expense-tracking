package com.uptimecrew.expense;

import static org.springframework.security.test.web.servlet.request.SecurityMockMvcRequestPostProcessors.jwt;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.get;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.post;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.jsonPath;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.status;

import java.math.BigDecimal;
import java.nio.file.Files;
import java.nio.file.Path;
import java.sql.Connection;
import java.sql.DriverManager;
import java.sql.Statement;
import java.util.List;
import java.util.UUID;

import org.junit.jupiter.api.BeforeAll;
import org.junit.jupiter.api.Test;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.boot.test.autoconfigure.web.servlet.AutoConfigureMockMvc;
import org.springframework.boot.test.context.SpringBootTest;
import org.springframework.boot.testcontainers.service.connection.ServiceConnection;
import org.springframework.http.MediaType;
import org.springframework.security.core.authority.SimpleGrantedAuthority;
import org.springframework.test.context.ActiveProfiles;
import org.springframework.test.web.servlet.MockMvc;
import org.springframework.test.web.servlet.request.RequestPostProcessor;
import org.testcontainers.containers.GenericContainer;
import org.testcontainers.containers.MongoDBContainer;
import org.testcontainers.containers.PostgreSQLContainer;
import org.testcontainers.junit.jupiter.Container;
import org.testcontainers.junit.jupiter.Testcontainers;

import com.uptimecrew.expense.entity.SyntheticOrder;
import com.uptimecrew.expense.repository.SyntheticOrderRepository;
import com.uptimecrew.expense.repository.SyntheticRefundRepository;

/**
 * Controller-level integration test for the synthetic W7D4 orders + refunds surface.
 *
 * <p>Covers: authenticated GET, tenant scoping, refund happy path with UUID v4,
 * idempotency (same key → same refund_id), and rejection of non-v4 keys.
 */
@Testcontainers
@SpringBootTest(properties = {
        "spring.security.oauth2.resourceserver.jwt.issuer-uri=",
        "spring.security.oauth2.resourceserver.jwt.jwk-set-uri=http://localhost/.well-known/jwks.json"
})
@AutoConfigureMockMvc
@ActiveProfiles("test")
class OrderControllerIT {

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
    MockMvc mockMvc;

    @Autowired
    SyntheticOrderRepository orderRepository;

    @Autowired
    SyntheticRefundRepository refundRepository;

    @BeforeAll
    static void applySchema() throws Exception {
        PG.start();
        waitForPostgres();

        String v1 = Files.readString(Path.of("db/V1__schema.sql"));
        String v5 = Files.readString(Path.of(
                "expense-api/src/main/resources/db/migration/V5__orders_refunds.sql"));
        try (Connection conn = DriverManager.getConnection(
                        PG.getJdbcUrl(), PG.getUsername(), PG.getPassword());
             Statement stmt = conn.createStatement()) {
            stmt.execute(v1);
            stmt.execute(v5);
        }
    }

    private RequestPostProcessor readerJwt() {
        return jwt()
                .jwt(j -> j
                        .subject("orders-reader")
                        .claim("scope", "orders.read")
                        .claim("roles", List.of("ORDERS_READER")))
                .authorities(
                        new SimpleGrantedAuthority("SCOPE_orders.read"),
                        new SimpleGrantedAuthority("ROLE_ORDERS_READER"));
    }

    private RequestPostProcessor writerJwt() {
        return jwt()
                .jwt(j -> j
                        .subject("orders-writer")
                        .claim("scope", "orders.write")
                        .claim("roles", List.of("ORDERS_WRITER")))
                .authorities(
                        new SimpleGrantedAuthority("SCOPE_orders.write"),
                        new SimpleGrantedAuthority("ROLE_ORDERS_WRITER"));
    }

    @Test
    void getOrder_returns200_forSeededOrder() throws Exception {
        // The seed row from V5 is asserted so a regression in the migration would surface here.
        mockMvc.perform(get("/api/v1/orders/{id}", "ord-synth-9001")
                        .header("X-Tenant-Id", "tenant-a")
                        .with(readerJwt()))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.orderId").value("ord-synth-9001"))
                .andExpect(jsonPath("$.tenantId").value("tenant-a"))
                .andExpect(jsonPath("$.status").value("OPEN"));
    }

    @Test
    void getOrder_returns404_forWrongTenant() throws Exception {
        mockMvc.perform(get("/api/v1/orders/{id}", "ord-synth-9001")
                        .header("X-Tenant-Id", "tenant-b")
                        .with(readerJwt()))
                .andExpect(status().isNotFound());
    }

    @Test
    void getOrder_returns401_whenAnonymous() throws Exception {
        mockMvc.perform(get("/api/v1/orders/{id}", "ord-synth-9001")
                        .header("X-Tenant-Id", "tenant-a"))
                .andExpect(status().isUnauthorized());
    }

    @Test
    void createRefund_isIdempotent_forSameKey() throws Exception {
        String orderId = "ord-idem-" + UUID.randomUUID();
        orderRepository.save(new SyntheticOrder(
                orderId, "tenant-a", new BigDecimal("50.00"), "OPEN"));

        String key = UUID.randomUUID().toString();
        String body = """
                {"amount": 10.00, "reason": "duplicate charge",
                 "tenant_id": "tenant-a", "idempotency_key": "%s"}
                """.formatted(key);

        String first = mockMvc.perform(post("/api/v1/orders/{id}/refunds", orderId)
                        .header("Idempotency-Key", key)
                        .contentType(MediaType.APPLICATION_JSON)
                        .content(body)
                        .with(writerJwt()))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.orderId").value(orderId))
                .andReturn().getResponse().getContentAsString();

        String second = mockMvc.perform(post("/api/v1/orders/{id}/refunds", orderId)
                        .header("Idempotency-Key", key)
                        .contentType(MediaType.APPLICATION_JSON)
                        .content(body)
                        .with(writerJwt()))
                .andExpect(status().isOk())
                .andReturn().getResponse().getContentAsString();

        // Same refundId across both calls proves idempotency.
        org.junit.jupiter.api.Assertions.assertEquals(first, second);
        // Ledger debited exactly once: only one refund row for that (order, key).
        org.junit.jupiter.api.Assertions.assertEquals(
                1,
                refundRepository.findAll().stream()
                        .filter(r -> orderId.equals(r.getOrderId()))
                        .count());
    }

    @Test
    void createRefund_rejects_nonV4Uuid() throws Exception {
        // A random-typed UUID.nameUUIDFromBytes uses v3; a v1 UUID starts with '1' in position 14.
        String v3 = UUID.nameUUIDFromBytes("not-v4".getBytes()).toString();
        String body = """
                {"amount": 10.00, "reason": "duplicate charge",
                 "tenant_id": "tenant-a", "idempotency_key": "%s"}
                """.formatted(v3);

        mockMvc.perform(post("/api/v1/orders/{id}/refunds", "ord-synth-9001")
                        .header("Idempotency-Key", v3)
                        .contentType(MediaType.APPLICATION_JSON)
                        .content(body)
                        .with(writerJwt()))
                .andExpect(status().isBadRequest());
    }

    @Test
    void createRefund_rejects_headerBodyMismatch() throws Exception {
        String headerKey = UUID.randomUUID().toString();
        String bodyKey = UUID.randomUUID().toString();
        String body = """
                {"amount": 5.00, "reason": "typo",
                 "tenant_id": "tenant-a", "idempotency_key": "%s"}
                """.formatted(bodyKey);

        mockMvc.perform(post("/api/v1/orders/{id}/refunds", "ord-synth-9001")
                        .header("Idempotency-Key", headerKey)
                        .contentType(MediaType.APPLICATION_JSON)
                        .content(body)
                        .with(writerJwt()))
                .andExpect(status().isBadRequest());
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
