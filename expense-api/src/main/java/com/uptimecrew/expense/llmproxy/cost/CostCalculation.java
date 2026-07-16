package com.uptimecrew.expense.llmproxy.cost;

import java.math.BigDecimal;
import java.math.RoundingMode;
import java.util.Objects;

/**
 * Pure cost math. Two invariants make this class exist as its own type:
 *
 *   1. All arithmetic is BigDecimal HALF_UP. There is no double
 *      anywhere in the cost path — no {@code doubleValue()}, no
 *      {@code Double.parseDouble}, no {@code Math.*}.
 *   2. The tally we store in Redis is an exact long in units of
 *      1e-5 USD ("cost_usd_e5"). The conversion is deliberate:
 *      {@code setScale(5, HALF_UP).movePointRight(5).longValueExact()}.
 *      Any overflow throws — we would rather fail loud than silently
 *      truncate a billion-dollar bug.
 */
public final class CostCalculation {

    private static final int USD_E5_SCALE = 5;

    public record Result(BigDecimal costUsd, long costUsdE5) {}

    private CostCalculation() {}

    public static Result compute(PriceBook.Price price, long inputTokens, long outputTokens) {
        Objects.requireNonNull(price, "price");
        if (inputTokens < 0 || outputTokens < 0) {
            throw new IllegalArgumentException(
                "token counts must be non-negative: input=" + inputTokens + " output=" + outputTokens);
        }

        BigDecimal inputCost = price.inputUsdPerToken().multiply(BigDecimal.valueOf(inputTokens));
        BigDecimal outputCost = price.outputUsdPerToken().multiply(BigDecimal.valueOf(outputTokens));

        BigDecimal totalUsd = inputCost.add(outputCost).setScale(USD_E5_SCALE, RoundingMode.HALF_UP);

        long e5 = totalUsd.movePointRight(USD_E5_SCALE).longValueExact();
        return new Result(totalUsd, e5);
    }
}
