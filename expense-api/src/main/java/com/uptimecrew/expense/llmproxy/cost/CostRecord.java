package com.uptimecrew.expense.llmproxy.cost;

import java.math.BigDecimal;
import java.util.Objects;

/**
 * One record per upstream LLM call. Immutable value object.
 *
 * costUsd is stored as BigDecimal (not double) even though EMF will
 * eventually serialize it — the middleware never rounds to a float
 * along the way.
 */
public record CostRecord(
    String service,
    String tenant,
    String feature,
    String modelId,
    long inputTokens,
    long outputTokens,
    BigDecimal costUsd,
    long costUsdE5,
    long latencyMs,
    boolean success
) {
    public CostRecord {
        Objects.requireNonNull(service, "service");
        Objects.requireNonNull(tenant, "tenant");
        Objects.requireNonNull(feature, "feature");
        Objects.requireNonNull(modelId, "modelId");
        Objects.requireNonNull(costUsd, "costUsd");
        if (inputTokens < 0 || outputTokens < 0 || latencyMs < 0) {
            throw new IllegalArgumentException("counters must be non-negative");
        }
    }
}
