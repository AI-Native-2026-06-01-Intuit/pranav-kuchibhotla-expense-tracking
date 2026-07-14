package com.uptimecrew.expense.llmproxy.cost;

import java.math.BigDecimal;
import java.util.Map;
import java.util.Objects;

/**
 * Static per-model USD price list, quoted as dollars per token so
 * arithmetic stays in BigDecimal end-to-end. The middleware never
 * touches double for money — see the cost-author audit in COST.md.
 *
 * Prices are quoted per single token (not per 1K) so token counts can
 * multiply directly without a divide-by-1000 rounding step. Values
 * come from the vendor's published rate card at the time of writing;
 * update in code, not at runtime, because a mid-flight price change
 * would silently rewrite historical CostUsdE5 accounting.
 */
public final class PriceBook {

    public record Price(BigDecimal inputUsdPerToken, BigDecimal outputUsdPerToken) {
        public Price {
            Objects.requireNonNull(inputUsdPerToken, "inputUsdPerToken");
            Objects.requireNonNull(outputUsdPerToken, "outputUsdPerToken");
            if (inputUsdPerToken.signum() < 0 || outputUsdPerToken.signum() < 0) {
                throw new IllegalArgumentException("prices must be non-negative");
            }
        }
    }

    private final Map<String, Price> prices;

    public PriceBook(Map<String, Price> prices) {
        this.prices = Map.copyOf(Objects.requireNonNull(prices, "prices"));
    }

    public static PriceBook defaults() {
        return new PriceBook(Map.of(
            "claude-sonnet-4-5", new Price(
                new BigDecimal("0.000003"),
                new BigDecimal("0.000015")
            ),
            "claude-haiku-4-5", new Price(
                new BigDecimal("0.000001"),
                new BigDecimal("0.000005")
            ),
            "claude-opus-4-7", new Price(
                new BigDecimal("0.000015"),
                new BigDecimal("0.000075")
            )
        ));
    }

    public Price priceFor(String modelId) {
        Price p = prices.get(Objects.requireNonNull(modelId, "modelId"));
        if (p == null) {
            throw new IllegalArgumentException("no price registered for modelId=" + modelId);
        }
        return p;
    }
}
