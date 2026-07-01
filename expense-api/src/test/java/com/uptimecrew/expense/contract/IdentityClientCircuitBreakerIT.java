package com.uptimecrew.expense.contract;

import static com.github.tomakehurst.wiremock.client.WireMock.aResponse;
import static com.github.tomakehurst.wiremock.client.WireMock.get;
import static com.github.tomakehurst.wiremock.client.WireMock.getRequestedFor;
import static com.github.tomakehurst.wiremock.client.WireMock.urlPathEqualTo;
import static com.github.tomakehurst.wiremock.core.WireMockConfiguration.wireMockConfig;
import static org.assertj.core.api.Assertions.assertThat;
import static org.springframework.security.test.web.servlet.request.SecurityMockMvcRequestPostProcessors.jwt;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.post;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.jsonPath;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.status;

import java.nio.file.Files;
import java.nio.file.Path;
import java.sql.Connection;
import java.sql.DriverManager;
import java.sql.Statement;
import java.util.List;
import java.util.UUID;

import org.junit.jupiter.api.BeforeAll;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.extension.RegisterExtension;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.boot.test.autoconfigure.web.servlet.AutoConfigureMockMvc;
import org.springframework.boot.test.context.SpringBootTest;
import org.springframework.boot.testcontainers.service.connection.ServiceConnection;
import org.springframework.security.core.authority.SimpleGrantedAuthority;
import org.springframework.test.context.ActiveProfiles;
import org.springframework.test.web.servlet.MockMvc;
import org.springframework.test.web.servlet.request.MockMvcRequestBuilders;
import org.testcontainers.containers.GenericContainer;
import org.testcontainers.containers.MongoDBContainer;
import org.testcontainers.containers.PostgreSQLContainer;
import org.testcontainers.junit.jupiter.Container;
import org.testcontainers.junit.jupiter.Testcontainers;

import com.github.tomakehurst.wiremock.junit5.WireMockExtension;
import com.uptimecrew.expense.clients.IdentityProfile;
import com.uptimecrew.expense.clients.IdentityService;

import io.github.resilience4j.circuitbreaker.CircuitBreaker;
import io.github.resilience4j.circuitbreaker.CircuitBreakerRegistry;

@Testcontainers
@SpringBootTest(
    webEnvironment = SpringBootTest.WebEnvironment.RANDOM_PORT,
    properties = {
        "spring.security.oauth2.resourceserver.jwt.issuer-uri=",
        "spring.security.oauth2.resourceserver.jwt.jwk-set-uri=http://localhost/.well-known/jwks.json"
    })
@AutoConfigureMockMvc
@ActiveProfiles("test")
class IdentityClientCircuitBreakerIT {

    @RegisterExtension
    static final WireMockExtension WM = WireMockExtension.newInstance()
            .options(wireMockConfig().port(8090))
            .build();

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
    IdentityService identityService;

    @Autowired
    CircuitBreakerRegistry circuitBreakerRegistry;

    @Autowired
    MockMvc mockMvc;

    @BeforeAll
    static void applyPostgresSchema() throws Exception {
        PG.start();
        String schemaSql = Files.readString(Path.of("db/V1__schema.sql"));
        try (Connection conn = DriverManager.getConnection(
                        PG.getJdbcUrl(), PG.getUsername(), PG.getPassword());
             Statement stmt = conn.createStatement()) {
            stmt.execute(schemaSql);
        }
    }

    @BeforeEach
    void resetState() {
        circuitBreakerRegistry.circuitBreaker("identity").reset();
        WM.resetAll();
    }

    @Test
    void getProfile_returnsBody_whenIdentityIs200() {
        WM.stubFor(get(urlPathEqualTo("/identity/u-1/profile"))
                .willReturn(aResponse()
                        .withStatus(200)
                        .withHeader("Content-Type", "application/json")
                        .withBody("{\"id\":\"u-1\",\"displayName\":\"Pat\",\"region\":\"us-east-1\"}")));

        IdentityProfile profile = identityService.getProfile("u-1");

        assertThat(profile).isEqualTo(new IdentityProfile("u-1", "Pat", "us-east-1"));
    }

    @Test
    void circuitOpens_after_repeated_5xx() {
        WM.stubFor(get(urlPathEqualTo("/identity/u-2/profile"))
                .willReturn(aResponse().withStatus(500)));

        CircuitBreaker breaker = circuitBreakerRegistry.circuitBreaker("identity");

        for (int i = 0; i < 20; i++) {
            identityService.getProfile("u-2");
            if (breaker.getState() == CircuitBreaker.State.OPEN) {
                break;
            }
        }

        assertThat(breaker.getState()).isEqualTo(CircuitBreaker.State.OPEN);

        int callsBefore = WM.getAllServeEvents().size();

        IdentityProfile fallback = identityService.getProfile("u-2");

        int callsAfter = WM.getAllServeEvents().size();
        assertThat(callsAfter).isEqualTo(callsBefore);
        assertThat(fallback.displayName()).isEmpty();
        assertThat(fallback.region()).isEqualTo("unknown");
    }

    @Test
    void summary_returns200_andIncludesProfileDisplayName() throws Exception {
        WM.stubFor(get(urlPathEqualTo("/identity/u-3/profile"))
                .willReturn(aResponse()
                        .withStatus(200)
                        .withHeader("Content-Type", "application/json")
                        .withBody("{\"id\":\"u-3\",\"displayName\":\"Sam\",\"region\":\"us-east-1\"}")));

        mockMvc.perform(post("/api/v1/merchants/{id}/summary", "abc")
                        .header("Idempotency-Key", UUID.randomUUID().toString())
                        .with(jwt()
                                .jwt(j -> j
                                        .subject("u-3")
                                        .claim("scope", "merchants.read")
                                        .claim("roles", List.of("MERCHANT_READER")))
                                .authorities(
                                        new SimpleGrantedAuthority("SCOPE_merchants.read"),
                                        new SimpleGrantedAuthority("ROLE_MERCHANT_READER"))))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.summary").value("Stub LLM summary for abc"))
                .andExpect(jsonPath("$.displayName").value("Sam"));

        WM.verify(getRequestedFor(urlPathEqualTo("/identity/u-3/profile")));
    }

    @Test
    void openApiDoc_exposesV1Path() throws Exception {
        mockMvc.perform(MockMvcRequestBuilders.get("/v3/api-docs"))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.paths['/api/v1/merchants/{id}']").exists())
                .andExpect(jsonPath("$.components.securitySchemes.bearer-jwt.scheme").value("bearer"));
    }
}
