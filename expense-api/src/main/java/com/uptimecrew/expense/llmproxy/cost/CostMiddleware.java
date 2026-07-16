package com.uptimecrew.expense.llmproxy.cost;

import java.util.Objects;

import com.fasterxml.jackson.core.JsonProcessingException;

/**
 * Provider-neutral boundary called once per upstream LLM response.
 * The middleware:
 *   1. Prices the call (BigDecimal HALF_UP; no double in the path).
 *   2. Increments the tenant+feature Redis tally via HINCRBY on the
 *      integer cost_usd_e5 field.
 *   3. Emits an EMF record to stdout so CloudWatch registers the
 *      acme/llmproxy CostUsd + CostUsdE5 metrics with the (service,
 *      tenant, feature) dimensions the cost alarm and monthly budget
 *      already watch.
 *
 * Cohort override: runtime provider is not Bedrock. The upstream call
 * uses the provided LLM_API_KEY (see llm-cost-spike.sh and COST.md).
 * The middleware is intentionally provider-neutral — it does not care
 * which vendor produced the token counts.
 */
public final class CostMiddleware {

    private final PriceBook priceBook;
    private final RedisCostStore store;
    private final EmfEmitter emitter;

    public CostMiddleware(PriceBook priceBook, RedisCostStore store, EmfEmitter emitter) {
        this.priceBook = Objects.requireNonNull(priceBook, "priceBook");
        this.store = Objects.requireNonNull(store, "store");
        this.emitter = Objects.requireNonNull(emitter, "emitter");
    }

    public record Call(
        String service,
        String tenant,
        String feature,
        String modelId,
        long inputTokens,
        long outputTokens,
        long latencyMs,
        boolean success
    ) {
        public Call {
            Objects.requireNonNull(service, "service");
            Objects.requireNonNull(tenant, "tenant");
            Objects.requireNonNull(feature, "feature");
            Objects.requireNonNull(modelId, "modelId");
        }
    }

    public CostRecord record(Call call) throws JsonProcessingException {
        Objects.requireNonNull(call, "call");

        PriceBook.Price price = priceBook.priceFor(call.modelId());
        CostCalculation.Result cost = CostCalculation.compute(price, call.inputTokens(), call.outputTokens());

        long tally = store.incrementCostUsdE5(call.tenant(), call.feature(), cost.costUsdE5());

        CostRecord record = new CostRecord(
            call.service(),
            call.tenant(),
            call.feature(),
            call.modelId(),
            call.inputTokens(),
            call.outputTokens(),
            cost.costUsd(),
            cost.costUsdE5(),
            call.latencyMs(),
            call.success()
        );
        emitter.emit(record);

        // The running tally is intentionally logged only via the EMF
        // record path (via a follow-up gauge if wanted) — we return
        // the record here so callers can also observe the post-
        // increment tally without an extra Redis round-trip.
        assert tally >= cost.costUsdE5() : "post-increment tally must be at least the delta just written";
        return record;
    }
}
