package com.uptimecrew.expense;

import static org.assertj.core.api.Assertions.assertThat;
import static org.mockito.ArgumentMatchers.anyString;
import static org.mockito.Mockito.RETURNS_DEEP_STUBS;
import static org.mockito.Mockito.mock;
import static org.mockito.Mockito.when;

import java.io.InputStream;
import java.math.BigDecimal;
import java.nio.file.Files;
import java.nio.file.Path;
import java.sql.Connection;
import java.sql.DriverManager;
import java.sql.Statement;
import java.time.Instant;
import java.util.ArrayList;
import java.util.List;
import java.util.Set;

import org.junit.jupiter.api.BeforeAll;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.ai.chat.client.ChatClient;
import org.springframework.boot.test.autoconfigure.graphql.tester.AutoConfigureHttpGraphQlTester;
import org.springframework.boot.test.context.SpringBootTest;
import org.springframework.boot.test.context.TestConfiguration;
import org.springframework.boot.testcontainers.service.connection.ServiceConnection;
import org.springframework.context.annotation.Bean;
import org.springframework.context.annotation.Import;
import org.springframework.context.annotation.Primary;
import org.springframework.core.io.ClassPathResource;
import org.springframework.graphql.test.tester.HttpGraphQlTester;
import org.springframework.test.annotation.DirtiesContext;
import org.springframework.test.context.ActiveProfiles;
import org.testcontainers.containers.GenericContainer;
import org.testcontainers.containers.MongoDBContainer;
import org.testcontainers.containers.PostgreSQLContainer;
import org.testcontainers.junit.jupiter.Container;
import org.testcontainers.junit.jupiter.Testcontainers;

import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.ObjectMapper;
import com.networknt.schema.JsonSchema;
import com.networknt.schema.JsonSchemaFactory;
import com.networknt.schema.SpecVersion;
import com.networknt.schema.ValidationMessage;
import com.uptimecrew.expense.graphql.MerchantSummary;
import com.uptimecrew.expense.readmodel.MerchantReadModel;
import com.uptimecrew.expense.readmodel.MerchantReadModel.EmbeddedTransaction;
import com.uptimecrew.expense.readmodel.MerchantReadModelRepository;

@Testcontainers
@SpringBootTest(webEnvironment = SpringBootTest.WebEnvironment.RANDOM_PORT)
@AutoConfigureHttpGraphQlTester
@ActiveProfiles("test")
@Import(MerchantGraphQlIT.StubChatClientConfig.class)
@DirtiesContext(classMode = DirtiesContext.ClassMode.AFTER_CLASS)
class MerchantGraphQlIT {

    static final MerchantSummary STUB_SUMMARY =
            new MerchantSummary("5812", 42.50, 3, "MEALS");

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
    HttpGraphQlTester graphQlTester;

    @Autowired
    MerchantReadModelRepository readModelRepository;

    @Autowired
    ObjectMapper objectMapper;

    @BeforeAll
    static void applyPostgresSchema() throws Exception {
        PG.start();
        waitForPostgres();
        String v1 = Files.readString(Path.of("db/V1__schema.sql"));
        String v3 = Files.readString(
                Path.of("src/main/resources/db/migration/V3__event_outbox.sql"));
        try (Connection conn = DriverManager.getConnection(
                        PG.getJdbcUrl(), PG.getUsername(), PG.getPassword());
             Statement stmt = conn.createStatement()) {
            stmt.execute(v1);
            stmt.execute(v3);
        }
    }

    @BeforeEach
    void seedMongo() {
        readModelRepository.deleteAll();
        readModelRepository.save(buildMerchant(
                "seeded-id-1", "Seeded Merchant 1", "5812",
                Instant.parse("2026-06-01T00:00:00Z"),
                new EmbeddedTransaction(
                        "tx-seeded-1-a", "acct-1", new BigDecimal("10.00"),
                        "DEDUCTIBLE",
                        Instant.parse("2026-06-01T00:00:00Z"),
                        Instant.parse("2026-06-01T00:00:00Z"))));
        for (int i = 2; i <= 5; i++) {
            readModelRepository.save(buildMerchant(
                    "seeded-id-" + i, "Seeded Merchant " + i, "5812",
                    Instant.parse("2026-06-0" + i + "T00:00:00Z"),
                    new EmbeddedTransaction(
                            "tx-seeded-" + i + "-a", "acct-" + i,
                            new BigDecimal("20.00"), "DEDUCTIBLE",
                            Instant.parse("2026-06-0" + i + "T00:00:00Z"),
                            Instant.parse("2026-06-0" + i + "T00:00:00Z"))));
        }
    }

    @Test
    void query_merchant_returnsSeedDocument() {
        graphQlTester.document("query { merchant(id: \"seeded-id-1\") { id } }")
                .execute()
                .path("merchant.id").entity(String.class).isEqualTo("seeded-id-1");
    }

    @Test
    void batchMapping_resolves_lines_inOneRound() {
        List<MerchantProjection> merchants = graphQlTester.document("""
                query {
                  latestMerchants(limit: 5) {
                    id
                    lines { id description amount }
                  }
                }
                """)
                .execute()
                .path("latestMerchants").entityList(MerchantProjection.class).get();

        assertThat(merchants).hasSize(5);
        for (MerchantProjection m : merchants) {
            assertThat(m.lines()).isNotNull();
        }
        MerchantProjection first = merchants.get(0);
        assertThat(first.lines()).isNotEmpty();
        LineProjection firstLine = first.lines().get(0);
        assertThat(firstLine.id()).isNotBlank();
        assertThat(firstLine.description()).isNotBlank();
        assertThat(firstLine.amount()).isNotNull();
    }

    @Test
    void summarizeMerchant_returnsStructuredOutput_andMatchesSchema() throws Exception {
        MerchantSummary response = graphQlTester.document("""
                mutation {
                  summarizeMerchant(id: "seeded-id-1") {
                    mccCode
                    totalSpend
                    transactionCount
                    primaryCategory
                  }
                }
                """)
                .execute()
                .path("summarizeMerchant").entity(MerchantSummary.class).get();

        assertThat(response.mccCode()).isEqualTo("5812");
        assertThat(response.totalSpend()).isEqualTo(42.5);
        assertThat(response.transactionCount()).isEqualTo(3);
        assertThat(response.primaryCategory()).isEqualTo("MEALS");

        JsonSchema schema;
        try (InputStream in =
                     new ClassPathResource("schemas/MerchantSummary.schema.json").getInputStream()) {
            schema = JsonSchemaFactory.getInstance(SpecVersion.VersionFlag.V202012)
                    .getSchema(in);
        }
        JsonNode node = objectMapper.valueToTree(response);
        Set<ValidationMessage> errors = schema.validate(node);
        assertThat(errors).isEmpty();
    }

    private static MerchantReadModel buildMerchant(String id,
                                                   String displayName,
                                                   String mccCode,
                                                   Instant createdAt,
                                                   EmbeddedTransaction... txs) {
        List<EmbeddedTransaction> embedded = new ArrayList<>();
        for (EmbeddedTransaction t : txs) {
            embedded.add(t);
        }
        return new MerchantReadModel(
                id, displayName, displayName.toLowerCase(), "DEDUCTIBLE",
                mccCode, createdAt, embedded);
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

    record MerchantProjection(String id, List<LineProjection> lines) {}
    record LineProjection(String id, String description, Double amount) {}

    // Replaces the auto-configured Anthropic ChatClient.Builder so the real
    // LlmSummaryService runs end-to-end (prompt build + JSON Schema gate)
    // without contacting Anthropic. Deep-stubs the fluent chain so
    // chatClient.prompt().user(...).call().entity(MerchantSummary.class)
    // resolves to the deterministic STUB_SUMMARY.
    @TestConfiguration
    static class StubChatClientConfig {
        @Bean
        @Primary
        ChatClient.Builder stubChatClientBuilder() {
            ChatClient client = mock(ChatClient.class, RETURNS_DEEP_STUBS);
            when(client.prompt().user(anyString()).call().entity(MerchantSummary.class))
                    .thenReturn(STUB_SUMMARY);
            ChatClient.Builder builder = mock(ChatClient.Builder.class);
            when(builder.build()).thenReturn(client);
            return builder;
        }
    }
}
