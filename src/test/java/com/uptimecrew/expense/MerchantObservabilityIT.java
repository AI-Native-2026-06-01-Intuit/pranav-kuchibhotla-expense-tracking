package com.uptimecrew.expense;

import static org.assertj.core.api.Assertions.assertThat;
import static org.awaitility.Awaitility.await;
import static org.mockito.ArgumentMatchers.anyString;
import static org.mockito.Mockito.RETURNS_DEEP_STUBS;
import static org.mockito.Mockito.mock;
import static org.mockito.Mockito.when;
import static org.springframework.security.test.web.servlet.request.SecurityMockMvcRequestPostProcessors.jwt;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.get;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.status;

import java.math.BigDecimal;
import java.nio.file.Files;
import java.nio.file.Path;
import java.sql.Connection;
import java.sql.DriverManager;
import java.sql.Statement;
import java.time.Duration;
import java.time.Instant;
import java.time.LocalDate;
import java.util.List;
import java.util.Locale;
import java.util.UUID;

import org.junit.jupiter.api.BeforeAll;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;
import org.springframework.ai.chat.client.ChatClient;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.boot.test.autoconfigure.graphql.tester.AutoConfigureHttpGraphQlTester;
import org.springframework.boot.test.context.SpringBootTest;
import org.springframework.boot.test.context.TestConfiguration;
import org.springframework.boot.testcontainers.service.connection.ServiceConnection;
import org.springframework.context.annotation.Bean;
import org.springframework.context.annotation.Import;
import org.springframework.context.annotation.Primary;
import org.springframework.graphql.test.tester.HttpGraphQlTester;
import org.springframework.security.core.authority.SimpleGrantedAuthority;
import org.springframework.test.annotation.DirtiesContext;
import org.springframework.test.context.ActiveProfiles;
import org.springframework.test.context.DynamicPropertyRegistry;
import org.springframework.test.context.DynamicPropertySource;
import org.springframework.test.web.servlet.MockMvc;
import org.testcontainers.containers.GenericContainer;
import org.testcontainers.containers.KafkaContainer;
import org.testcontainers.containers.MongoDBContainer;
import org.testcontainers.containers.PostgreSQLContainer;
import org.testcontainers.junit.jupiter.Container;
import org.testcontainers.junit.jupiter.Testcontainers;
import org.testcontainers.utility.DockerImageName;

import com.uptimecrew.expense.graphql.MerchantSummary;
import com.uptimecrew.expense.model.Transaction;
import com.uptimecrew.expense.readmodel.MerchantReadModel;
import com.uptimecrew.expense.readmodel.MerchantReadModel.EmbeddedTransaction;
import com.uptimecrew.expense.readmodel.MerchantReadModelRepository;
import com.uptimecrew.expense.service.ExpenseClassificationService;

import io.opentelemetry.api.OpenTelemetry;
import io.opentelemetry.api.trace.Span;
import io.opentelemetry.api.trace.Tracer;
import io.opentelemetry.context.Scope;
import io.opentelemetry.api.trace.propagation.W3CTraceContextPropagator;
import io.opentelemetry.context.propagation.ContextPropagators;
import io.opentelemetry.sdk.OpenTelemetrySdk;
import io.opentelemetry.sdk.testing.exporter.InMemorySpanExporter;
import io.opentelemetry.sdk.trace.SdkTracerProvider;
import io.opentelemetry.sdk.trace.data.SpanData;
import io.opentelemetry.sdk.trace.export.SimpleSpanProcessor;

@Testcontainers
@SpringBootTest(
        webEnvironment = SpringBootTest.WebEnvironment.RANDOM_PORT,
        properties = {
                // The default test profile turns OTel off defensively so other ITs don't
                // need a collector. Re-enable here so spans actually flow into the
                // in-memory exporter wired by ObservabilityTestConfig.
                "otel.traces.exporter=none",
                "otel.traces.sampler=always_on",
                "otel.instrumentation.spring-kafka.enabled=true",
                "otel.instrumentation.kafka.enabled=true",
                // Lets the test-config @Primary OpenTelemetry win over the autoconfigured
                // SDK without Spring complaining about duplicate bean definitions.
                "spring.main.allow-bean-definition-overriding=true",
                "spring.security.oauth2.resourceserver.jwt.issuer-uri=",
                "spring.security.oauth2.resourceserver.jwt.jwk-set-uri=http://localhost/.well-known/jwks.json"
        })
@AutoConfigureHttpGraphQlTester
@ActiveProfiles("test")
@Import(MerchantObservabilityIT.ObservabilityTestConfig.class)
@DirtiesContext(classMode = DirtiesContext.ClassMode.AFTER_CLASS)
class MerchantObservabilityIT {

    private static final String TOPIC = "merchants.events";

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

    @Container
    static final KafkaContainer KAFKA =
            new KafkaContainer(DockerImageName.parse("confluentinc/cp-kafka:7.6.0"));

    @DynamicPropertySource
    static void kafkaProps(DynamicPropertyRegistry registry) {
        registry.add("spring.kafka.bootstrap-servers", KAFKA::getBootstrapServers);
        registry.add("spring.kafka.producer.bootstrap-servers", KAFKA::getBootstrapServers);
        registry.add("spring.kafka.consumer.bootstrap-servers", KAFKA::getBootstrapServers);
    }

    @Autowired
    InMemorySpanExporter spanExporter;

    @Autowired
    OpenTelemetry openTelemetry;

    @Autowired
    MockMvc mockMvc;

    @Autowired
    HttpGraphQlTester graphQlTester;

    @Autowired
    ExpenseClassificationService classificationService;

    @Autowired
    MerchantReadModelRepository readModelRepository;

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
    void resetSpans() {
        spanExporter.reset();
    }

    @Test
    void httpRequest_emits_serverSpan_and_jdbcChildSpan() throws Exception {
        Transaction tx = new Transaction(
                "txn-obs-http-" + UUID.randomUUID(),
                "acct-obs-http",
                new BigDecimal("19.99"),
                "Observability HTTP Merchant " + UUID.randomUUID(),
                LocalDate.of(2026, 3, 1));
        classificationService.classify(tx);
        String id = "merchant-" + tx.merchantName().trim().toLowerCase(Locale.ROOT);
        spanExporter.reset();

        mockMvc.perform(get("/api/v1/merchants/{id}", id)
                        .with(jwt()
                                .jwt(j -> j
                                        .subject("obs-user")
                                        .claim("scope", "merchants.read")
                                        .claim("roles", List.of("MERCHANT_READER")))
                                .authorities(
                                        new SimpleGrantedAuthority("SCOPE_merchants.read"),
                                        new SimpleGrantedAuthority("ROLE_MERCHANT_READER"))))
                .andExpect(status().isOk());

        await().atMost(Duration.ofSeconds(15)).untilAsserted(() -> {
            List<SpanData> spans = spanExporter.getFinishedSpanItems();
            assertThat(spans).as("HTTP server span emitted").anyMatch(MerchantObservabilityIT::looksLikeServerSpan);
            assertThat(spans).as("JDBC/db span emitted").anyMatch(MerchantObservabilityIT::looksLikeDbSpan);

            String serverTraceId = spans.stream()
                    .filter(MerchantObservabilityIT::looksLikeServerSpan)
                    .findFirst()
                    .orElseThrow()
                    .getTraceId();
            assertThat(spans)
                    .filteredOn(MerchantObservabilityIT::looksLikeDbSpan)
                    .as("at least one JDBC span shares the server-span trace id")
                    .anyMatch(s -> serverTraceId.equals(s.getTraceId()));
        });
    }

    @Test
    void kafkaWriteThrough_singleTraceId_endToEnd() {
        Tracer tracer = openTelemetry.getTracer("test.kafka-write-through");
        String merchantName = "Observability Kafka " + UUID.randomUUID();
        String aggregateId = "merchant-" + merchantName.toLowerCase(Locale.ROOT);
        Transaction tx = new Transaction(
                "txn-obs-kafka-" + UUID.randomUUID(),
                "acct-obs-kafka",
                new BigDecimal("250.00"),
                merchantName,
                LocalDate.of(2026, 3, 2));

        Span root = tracer.spanBuilder("test.write_through").startSpan();
        try (Scope scope = root.makeCurrent()) {
            classificationService.classify(tx);
        } finally {
            root.end();
        }

        await().atMost(Duration.ofSeconds(20)).untilAsserted(() ->
                assertThat(readModelRepository.findById(aggregateId)).isPresent());

        await().atMost(Duration.ofSeconds(15)).untilAsserted(() -> {
            List<SpanData> spans = spanExporter.getFinishedSpanItems();

            assertThat(spans).as("a producer span exists for topic " + TOPIC)
                    .anyMatch(s -> looksLikeKafkaProducerSpan(s, TOPIC));
            assertThat(spans).as("a consumer span exists for topic " + TOPIC)
                    .anyMatch(s -> looksLikeKafkaConsumerSpan(s, TOPIC));
            assertThat(spans).as("a JDBC/db span exists for the write path")
                    .anyMatch(MerchantObservabilityIT::looksLikeDbSpan);
            assertThat(spans).as("a Mongo/read-model span exists for the consumer path")
                    .anyMatch(MerchantObservabilityIT::looksLikeMongoSpan);

            // Several outbox dispatches may run during this test (scheduler fires
            // every second), so multiple producer/consumer pairs exist. Assert
            // that at least one consumer span shares a trace id with some
            // producer span — that's sufficient evidence that traceparent
            // propagation works producer -> consumer for this pipeline.
            List<String> producerTraceIds = spans.stream()
                    .filter(s -> looksLikeKafkaProducerSpan(s, TOPIC))
                    .map(SpanData::getTraceId)
                    .toList();
            assertThat(spans)
                    .filteredOn(s -> looksLikeKafkaConsumerSpan(s, TOPIC))
                    .as("traceparent propagated producer -> consumer for at least one record")
                    .anyMatch(consumer -> producerTraceIds.contains(consumer.getTraceId()));
        });
    }

    @Test
    void llmSummarize_spanHasTokenAttributes() {
        String id = "obs-llm-" + UUID.randomUUID();
        readModelRepository.save(new MerchantReadModel(
                id,
                "Observability LLM Merchant",
                "observability llm merchant",
                "DEDUCTIBLE",
                "5812",
                Instant.parse("2026-06-01T00:00:00Z"),
                List.of(new EmbeddedTransaction(
                        "tx-obs-llm-1", "acct-obs-llm",
                        new BigDecimal("12.34"), "DEDUCTIBLE",
                        Instant.parse("2026-06-01T00:00:00Z"),
                        Instant.parse("2026-06-01T00:00:00Z")))));
        spanExporter.reset();

        graphQlTester.document("""
                        mutation { summarizeMerchant(id: "%s") {
                          mccCode totalSpend transactionCount primaryCategory
                        } }""".formatted(id))
                .execute()
                .path("summarizeMerchant.mccCode").entity(String.class).isEqualTo("5812");

        await().atMost(Duration.ofSeconds(15)).untilAsserted(() -> {
            SpanData llmSpan = spanExporter.getFinishedSpanItems().stream()
                    .filter(s -> "llm.summarize".equals(s.getName()))
                    .findFirst()
                    .orElseThrow(() -> new AssertionError("llm.summarize span not found"));

            String model = llmSpan.getAttributes()
                    .get(io.opentelemetry.api.common.AttributeKey.stringKey("llm.model"));
            String aggregateId = llmSpan.getAttributes()
                    .get(io.opentelemetry.api.common.AttributeKey.stringKey("llm.input.aggregate_id"));
            Long tokensIn = llmSpan.getAttributes()
                    .get(io.opentelemetry.api.common.AttributeKey.longKey("llm.tokens.in"));
            Long tokensOut = llmSpan.getAttributes()
                    .get(io.opentelemetry.api.common.AttributeKey.longKey("llm.tokens.out"));

            assertThat(model).isNotBlank();
            assertThat(aggregateId).isEqualTo(id);
            assertThat(tokensIn).isNotNull();
            assertThat(tokensOut).isNotNull();
        });
    }

    private static boolean looksLikeServerSpan(SpanData s) {
        return s.getKind() == io.opentelemetry.api.trace.SpanKind.SERVER;
    }

    private static boolean looksLikeDbSpan(SpanData s) {
        String scope = s.getInstrumentationScopeInfo().getName().toLowerCase(Locale.ROOT);
        String name = s.getName() == null ? "" : s.getName().toLowerCase(Locale.ROOT);
        return scope.contains("jdbc")
                || scope.contains("hikari")
                || scope.contains("datasource")
                || name.startsWith("select ")
                || name.startsWith("insert ")
                || name.startsWith("update ")
                || name.startsWith("delete ");
    }

    private static boolean looksLikeMongoSpan(SpanData s) {
        String scope = s.getInstrumentationScopeInfo().getName().toLowerCase(Locale.ROOT);
        return scope.contains("mongo");
    }

    private static boolean looksLikeKafkaProducerSpan(SpanData s, String topic) {
        if (s.getKind() != io.opentelemetry.api.trace.SpanKind.PRODUCER) {
            return false;
        }
        String name = s.getName() == null ? "" : s.getName();
        return name.contains(topic);
    }

    private static boolean looksLikeKafkaConsumerSpan(SpanData s, String topic) {
        if (s.getKind() != io.opentelemetry.api.trace.SpanKind.CONSUMER) {
            return false;
        }
        String name = s.getName() == null ? "" : s.getName();
        return name.contains(topic);
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

    @TestConfiguration
    static class ObservabilityTestConfig {

        @Bean
        InMemorySpanExporter inMemorySpanExporter() {
            return InMemorySpanExporter.create();
        }

        @Bean
        @Primary
        OpenTelemetry openTelemetry(InMemorySpanExporter exporter) {
            SdkTracerProvider tracerProvider = SdkTracerProvider.builder()
                    .addSpanProcessor(SimpleSpanProcessor.create(exporter))
                    .build();
            return OpenTelemetrySdk.builder()
                    .setTracerProvider(tracerProvider)
                    .setPropagators(ContextPropagators.create(W3CTraceContextPropagator.getInstance()))
                    .build();
        }

        // Replaces the auto-configured Anthropic ChatClient.Builder so the manual
        // llm.summarize span fires end-to-end without contacting Anthropic.
        // Deep-stubs the fluent chain so .entity(MerchantSummary.class) returns a
        // schema-valid MerchantSummary and .chatResponse() returns a deep-stubbed
        // ChatResponse whose Usage metadata yields null tokens — LlmSummaryService
        // null-checks and records 0L, which still satisfies the not-null assertions
        // in llmSummarize_spanHasTokenAttributes.
        @Bean
        @Primary
        ChatClient.Builder stubChatClientBuilder() {
            MerchantSummary stub = new MerchantSummary("5812", 42.50, 3, "MEALS");
            ChatClient client = mock(ChatClient.class, RETURNS_DEEP_STUBS);
            when(client.prompt().user(anyString()).call().entity(MerchantSummary.class))
                    .thenReturn(stub);
            ChatClient.Builder builder = mock(ChatClient.Builder.class);
            when(builder.build()).thenReturn(client);
            return builder;
        }
    }
}
