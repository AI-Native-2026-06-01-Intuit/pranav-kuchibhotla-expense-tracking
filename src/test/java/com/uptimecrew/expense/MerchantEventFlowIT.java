package com.uptimecrew.expense;

import static org.assertj.core.api.Assertions.assertThat;
import static org.awaitility.Awaitility.await;

import java.math.BigDecimal;
import java.nio.file.Files;
import java.nio.file.Path;
import java.sql.Connection;
import java.sql.DriverManager;
import java.sql.Statement;
import java.time.Duration;
import java.time.Instant;
import java.time.LocalDate;
import java.util.Collections;
import java.util.Comparator;
import java.util.List;
import java.util.Optional;
import java.util.Properties;
import java.util.UUID;

import org.apache.kafka.clients.consumer.ConsumerConfig;
import org.apache.kafka.clients.consumer.ConsumerRecord;
import org.apache.kafka.clients.consumer.ConsumerRecords;
import org.apache.kafka.clients.consumer.KafkaConsumer;
import org.apache.kafka.common.serialization.StringDeserializer;
import org.junit.jupiter.api.BeforeAll;
import org.junit.jupiter.api.Test;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.boot.test.context.SpringBootTest;
import org.springframework.boot.testcontainers.service.connection.ServiceConnection;
import org.springframework.kafka.core.KafkaTemplate;
import org.springframework.test.context.ActiveProfiles;
import org.springframework.test.context.DynamicPropertyRegistry;
import org.springframework.test.context.DynamicPropertySource;
import org.testcontainers.containers.GenericContainer;
import org.testcontainers.containers.KafkaContainer;
import org.testcontainers.containers.MongoDBContainer;
import org.testcontainers.containers.PostgreSQLContainer;
import org.testcontainers.junit.jupiter.Container;
import org.testcontainers.junit.jupiter.Testcontainers;
import org.testcontainers.utility.DockerImageName;

import com.fasterxml.jackson.databind.ObjectMapper;
import com.uptimecrew.expense.consumer.MerchantClassifiedEvent;
import com.uptimecrew.expense.model.Transaction;
import com.uptimecrew.expense.outbox.EventOutboxEntity;
import com.uptimecrew.expense.outbox.EventOutboxRepository;
import com.uptimecrew.expense.readmodel.MerchantReadModel;
import com.uptimecrew.expense.readmodel.MerchantReadModelRepository;
import com.uptimecrew.expense.service.ExpenseClassificationService;

@Testcontainers
@SpringBootTest
@ActiveProfiles("test")
class MerchantEventFlowIT {

    private static final String TOPIC = "merchants.events";
    private static final String DLT_TOPIC = "merchants.events.DLT";

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
    }

    @Autowired
    ExpenseClassificationService service;

    @Autowired
    EventOutboxRepository outboxRepository;

    @Autowired
    MerchantReadModelRepository readModelRepository;

    @Autowired
    KafkaTemplate<String, String> kafkaTemplate;

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

    @Test
    void write_publishes_to_kafka_via_outbox() throws Exception {
        String probeGroup = "probe-write-" + UUID.randomUUID();
        try (KafkaConsumer<String, String> probe = newProbe(probeGroup, TOPIC)) {
            probe.poll(Duration.ofMillis(500));

            Instant before = Instant.now().minusSeconds(1);

            Transaction tx = new Transaction(
                    "txn-flow-write-" + UUID.randomUUID(),
                    "acct-flow-001",
                    new BigDecimal("125.00"),
                    "EventFlow Write " + UUID.randomUUID(),
                    LocalDate.of(2026, 3, 1));

            service.classify(tx);

            await().atMost(Duration.ofSeconds(10)).untilAsserted(() -> {
                Optional<EventOutboxEntity> row = findNewOutboxRow(before);
                assertThat(row).isPresent();
                assertThat(row.get().getPublishedAt()).isNotNull();
            });

            String aggregateId = findNewOutboxRow(before).orElseThrow().getAggregateId();

            ConsumerRecord<String, String> record =
                    pollForKey(probe, aggregateId, Duration.ofSeconds(10));
            assertThat(record).isNotNull();
            assertThat(record.key()).isEqualTo(aggregateId);
            assertThat(record.value()).contains(aggregateId);
        }
    }

    @Test
    void consumer_updates_mongo_read_model() throws Exception {
        String aggregateId = "merchant-flow-consumer-" + UUID.randomUUID();
        MerchantClassifiedEvent event = new MerchantClassifiedEvent(
                aggregateId,
                "Consumer Test Display",
                "consumer test display",
                "consumer test display",
                "DEDUCTIBLE");
        String payload = objectMapper.writeValueAsString(event);

        kafkaTemplate.send(TOPIC, aggregateId, payload).get();

        await().atMost(Duration.ofSeconds(15)).untilAsserted(() ->
                assertThat(readModelRepository.findById(aggregateId)).isPresent());

        MerchantReadModel doc = readModelRepository.findById(aggregateId).orElseThrow();
        assertThat(doc.getDisplayName()).isEqualTo("Consumer Test Display");
        assertThat(doc.getMccCode()).isEqualTo("consumer test display");
    }

    @Test
    void poison_pill_routes_to_dlt_after_retries() throws Exception {
        String poisonKey = "poison-" + UUID.randomUUID();
        String dltGroup = "probe-dlt-" + UUID.randomUUID();
        try (KafkaConsumer<String, String> dltProbe = newProbe(dltGroup, DLT_TOPIC)) {
            dltProbe.poll(Duration.ofMillis(500));

            kafkaTemplate.send(TOPIC, poisonKey, "{not valid json").get();

            ConsumerRecord<String, String> dltRecord =
                    pollForKey(dltProbe, poisonKey, Duration.ofSeconds(25));
            assertThat(dltRecord).isNotNull();
            assertThat(dltRecord.key()).isEqualTo(poisonKey);
        }
    }

    private Optional<EventOutboxEntity> findNewOutboxRow(Instant since) {
        List<EventOutboxEntity> rows = outboxRepository.findAll();
        return rows.stream()
                .filter(r -> TOPIC.equals(r.getTopic()))
                .filter(r -> r.getOccurredAt() != null && !r.getOccurredAt().isBefore(since))
                .max(Comparator.comparing(EventOutboxEntity::getOccurredAt));
    }

    private static KafkaConsumer<String, String> newProbe(String groupId, String topic) {
        Properties props = new Properties();
        props.put(ConsumerConfig.BOOTSTRAP_SERVERS_CONFIG, KAFKA.getBootstrapServers());
        props.put(ConsumerConfig.GROUP_ID_CONFIG, groupId);
        props.put(ConsumerConfig.AUTO_OFFSET_RESET_CONFIG, "earliest");
        props.put(ConsumerConfig.ENABLE_AUTO_COMMIT_CONFIG, "false");
        props.put(ConsumerConfig.KEY_DESERIALIZER_CLASS_CONFIG, StringDeserializer.class);
        props.put(ConsumerConfig.VALUE_DESERIALIZER_CLASS_CONFIG, StringDeserializer.class);
        KafkaConsumer<String, String> consumer = new KafkaConsumer<>(props);
        consumer.subscribe(Collections.singletonList(topic));
        return consumer;
    }

    private static ConsumerRecord<String, String> pollForKey(
            KafkaConsumer<String, String> consumer, String key, Duration timeout) {
        long deadline = System.currentTimeMillis() + timeout.toMillis();
        while (System.currentTimeMillis() < deadline) {
            ConsumerRecords<String, String> records = consumer.poll(Duration.ofMillis(500));
            for (ConsumerRecord<String, String> r : records) {
                if (key.equals(r.key())) {
                    return r;
                }
            }
        }
        return null;
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
