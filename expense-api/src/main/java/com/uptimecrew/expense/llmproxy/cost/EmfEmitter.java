package com.uptimecrew.expense.llmproxy.cost;

import java.io.PrintStream;
import java.time.Clock;
import java.util.Objects;

import com.fasterxml.jackson.core.JsonProcessingException;
import com.fasterxml.jackson.databind.ObjectMapper;
import com.fasterxml.jackson.databind.node.ArrayNode;
import com.fasterxml.jackson.databind.node.ObjectNode;

/**
 * Emits a CloudWatch Embedded Metric Format (EMF) record to stdout,
 * one line per LLM call. The CloudWatch agent (or the container log
 * router) turns each line into a CloudWatch metric under namespace
 * acme/llmproxy without any additional API calls from the app.
 *
 * Two metrics are published per record:
 *   - CostUsd    (double) — human-readable dollars for dashboards
 *   - CostUsdE5  (long)   — the exact minor-units tally stored in
 *                           Redis, so a dashboard can reconstruct the
 *                           tally without floating-point drift
 *
 * Dimensions are (service, tenant, feature). modelId, success, and
 * latencyMs are non-dimensional properties on the same record, so
 * they show up as searchable log fields but don't multiply the
 * dimension cardinality (which would multiply cost).
 */
public final class EmfEmitter {

    private static final String NAMESPACE = "acme/llmproxy";
    private static final ObjectMapper MAPPER = new ObjectMapper();

    private final PrintStream out;
    private final Clock clock;

    public EmfEmitter() {
        this(System.out, Clock.systemUTC());
    }

    public EmfEmitter(PrintStream out, Clock clock) {
        this.out = Objects.requireNonNull(out, "out");
        this.clock = Objects.requireNonNull(clock, "clock");
    }

    public String emit(CostRecord record) throws JsonProcessingException {
        Objects.requireNonNull(record, "record");
        ObjectNode root = MAPPER.createObjectNode();

        ObjectNode aws = root.putObject("_aws");
        aws.put("Timestamp", clock.millis());
        ArrayNode cwMetrics = aws.putArray("CloudWatchMetrics");
        ObjectNode metricDef = cwMetrics.addObject();
        metricDef.put("Namespace", NAMESPACE);
        ArrayNode dimensionSets = metricDef.putArray("Dimensions");
        ArrayNode dims = dimensionSets.addArray();
        dims.add("service");
        dims.add("tenant");
        dims.add("feature");
        ArrayNode metrics = metricDef.putArray("Metrics");
        ObjectNode costUsd = metrics.addObject();
        costUsd.put("Name", "CostUsd");
        costUsd.put("Unit", "None");
        ObjectNode costE5 = metrics.addObject();
        costE5.put("Name", "CostUsdE5");
        costE5.put("Unit", "Count");

        root.put("service", record.service());
        root.put("tenant", record.tenant());
        root.put("feature", record.feature());
        root.put("modelId", record.modelId());
        root.put("success", record.success());
        root.put("latencyMs", record.latencyMs());
        root.put("inputTokens", record.inputTokens());
        root.put("outputTokens", record.outputTokens());
        root.put("CostUsd", record.costUsd());
        root.put("CostUsdE5", record.costUsdE5());

        String line = MAPPER.writeValueAsString(root);
        out.println(line);
        return line;
    }
}
