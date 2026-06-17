package com.uptimecrew.expense;

import static org.springframework.security.test.web.servlet.request.SecurityMockMvcRequestPostProcessors.jwt;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.get;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.header;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.status;

import java.nio.file.Files;
import java.nio.file.Path;
import java.sql.Connection;
import java.sql.DriverManager;
import java.sql.Statement;
import java.time.Instant;
import java.util.List;

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

import com.uptimecrew.expense.readmodel.MerchantReadModel;
import com.uptimecrew.expense.readmodel.MerchantReadModelRepository;

@Testcontainers
@SpringBootTest(properties = {
        // Override the placeholder issuer-uri from application.yml so Spring
        // Security can build a JwtDecoder bean without reaching the network.
        // The actual decoder is never invoked because spring-security-test's
        // jwt() post-processor injects authentication directly into the
        // SecurityContext, bypassing the BearerTokenAuthenticationFilter's
        // decode step.
        "spring.security.oauth2.resourceserver.jwt.issuer-uri=",
        "spring.security.oauth2.resourceserver.jwt.jwk-set-uri=http://localhost/.well-known/jwks.json"
})
@AutoConfigureMockMvc
@ActiveProfiles("test")
class MerchantSecurityIT {

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
    MerchantReadModelRepository readModelRepository;

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
    void getById_returns200_whenAuthenticatedWithScopeAndRole() throws Exception {
        String id = "merchant-security-200";
        readModelRepository.save(new MerchantReadModel(
                id,
                "Security 200 Merchant",
                "security 200 merchant",
                "UNKNOWN",
                "security 200 merchant",
                Instant.now(),
                List.of()));

        mockMvc.perform(get("/api/merchants/{id}", id)
                        .with(jwt()
                                .jwt(j -> j
                                        .subject("security-user")
                                        .claim("scope", "merchants.read")
                                        .claim("roles", List.of("MERCHANT_READER")))
                                .authorities(
                                        new SimpleGrantedAuthority("SCOPE_merchants.read"),
                                        new SimpleGrantedAuthority("ROLE_MERCHANT_READER"))))
                .andExpect(status().isOk());
    }

    @Test
    void getById_returns401_whenAnonymous() throws Exception {
        mockMvc.perform(get("/api/merchants/{id}", "test-id"))
                .andExpect(status().isUnauthorized());
    }

    @Test
    void getById_returns403_whenJwtMissingRole() throws Exception {
        mockMvc.perform(get("/api/merchants/{id}", "test-id")
                        .with(jwt()
                                .jwt(j -> j
                                        .subject("no-role-user")
                                        .claim("scope", "merchants.read")
                                        .claim("roles", List.of()))
                                .authorities(new SimpleGrantedAuthority("SCOPE_merchants.read"))))
                .andExpect(status().isForbidden());
    }

    @Test
    void summary_returns429_after10Calls() throws Exception {
        RequestPostProcessor jwtPostProcessor = jwt()
                .jwt(j -> j
                        .subject("rate-limit-user")
                        .claim("scope", "merchants.read")
                        .claim("roles", List.of("MERCHANT_READER")))
                .authorities(
                        new SimpleGrantedAuthority("SCOPE_merchants.read"),
                        new SimpleGrantedAuthority("ROLE_MERCHANT_READER"));

        for (int i = 0; i < 10; i++) {
            mockMvc.perform(get("/api/merchants/{id}/summary", "test-id")
                            .with(jwtPostProcessor))
                    .andExpect(status().isOk());
        }

        mockMvc.perform(get("/api/merchants/{id}/summary", "test-id")
                        .with(jwtPostProcessor))
                .andExpect(status().isTooManyRequests())
                .andExpect(header().string("Retry-After", "60"))
                .andExpect(header().string("Content-Type", MediaType.APPLICATION_JSON_VALUE));
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
