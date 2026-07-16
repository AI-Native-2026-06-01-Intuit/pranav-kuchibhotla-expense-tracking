package com.uptimecrew.expense.llmproxy.cost;

import static org.assertj.core.api.Assertions.assertThat;

import java.io.ByteArrayOutputStream;
import java.io.PrintStream;
import java.math.BigDecimal;
import java.nio.charset.StandardCharsets;
import java.time.Clock;
import java.time.Instant;
import java.time.ZoneOffset;

import org.junit.jupiter.api.Test;

import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.ObjectMapper;

class EmfEmitterTest {

    private static final ObjectMapper MAPPER = new ObjectMapper();

    @Test
    void emfRecordContainsRequiredDimensionsAndMetrics() throws Exception {
        ByteArrayOutputStream buf = new ByteArrayOutputStream();
        EmfEmitter emitter = new EmfEmitter(
            new PrintStream(buf, true, StandardCharsets.UTF_8),
            Clock.fixed(Instant.ofEpochMilli(1_700_000_000_000L), ZoneOffset.UTC)
        );

        CostRecord record = new CostRecord(
            "expense",
            "tenant-synth",
            "categorize-expense",
            "claude-sonnet-4-5",
            1_000L,
            250L,
            new BigDecimal("0.00675"),
            675L,
            42L,
            true
        );

        String line = emitter.emit(record);
        JsonNode json = MAPPER.readTree(line);

        assertThat(json.path("service").asText()).isEqualTo("expense");
        assertThat(json.path("tenant").asText()).isEqualTo("tenant-synth");
        assertThat(json.path("feature").asText()).isEqualTo("categorize-expense");
        assertThat(json.path("modelId").asText()).isEqualTo("claude-sonnet-4-5");
        assertThat(json.path("success").asBoolean()).isTrue();
        assertThat(json.path("latencyMs").asLong()).isEqualTo(42L);
        assertThat(json.path("CostUsdE5").asLong()).isEqualTo(675L);
        assertThat(json.path("CostUsd").decimalValue()).isEqualByComparingTo(new BigDecimal("0.00675"));

        JsonNode metricDef = json.path("_aws").path("CloudWatchMetrics").get(0);
        assertThat(metricDef.path("Namespace").asText()).isEqualTo("acme/llmproxy");

        JsonNode dims = metricDef.path("Dimensions").get(0);
        assertThat(dims).extracting(JsonNode::asText)
            .containsExactly("service", "tenant", "feature");

        JsonNode metrics = metricDef.path("Metrics");
        assertThat(metrics).hasSize(2);
        assertThat(metrics.get(0).path("Name").asText()).isEqualTo("CostUsd");
        assertThat(metrics.get(1).path("Name").asText()).isEqualTo("CostUsdE5");
    }
}
