package com.uptimecrew.expense.llmproxy.cost;

import static org.assertj.core.api.Assertions.assertThat;
import static org.assertj.core.api.Assertions.assertThatThrownBy;

import java.math.BigDecimal;

import org.junit.jupiter.api.Test;

class CostCalculationTest {

    private static final PriceBook.Price SONNET = new PriceBook.Price(
        new BigDecimal("0.000003"),
        new BigDecimal("0.000015")
    );

    @Test
    void thousandInputZeroOutputCostsThreeMillicents() {
        CostCalculation.Result result = CostCalculation.compute(SONNET, 1_000L, 0L);

        assertThat(result.costUsd()).isEqualByComparingTo(new BigDecimal("0.00300"));
        assertThat(result.costUsdE5()).isEqualTo(300L);
    }

    @Test
    void zeroInputThousandOutputCostsFifteenMillicents() {
        CostCalculation.Result result = CostCalculation.compute(SONNET, 0L, 1_000L);

        assertThat(result.costUsd()).isEqualByComparingTo(new BigDecimal("0.01500"));
        assertThat(result.costUsdE5()).isEqualTo(1_500L);
    }

    @Test
    void roundingHalfUpAtFifthDecimal() {
        // Price picked so the raw product lands on the fifth-decimal
        // half boundary: 1 * 0.000015 = 0.000015 -> HALF_UP -> 0.00002
        PriceBook.Price price = new PriceBook.Price(BigDecimal.ZERO, new BigDecimal("0.000015"));
        CostCalculation.Result result = CostCalculation.compute(price, 0L, 1L);

        assertThat(result.costUsd()).isEqualByComparingTo(new BigDecimal("0.00002"));
        assertThat(result.costUsdE5()).isEqualTo(2L);
    }

    @Test
    void overflowThrowsInsteadOfSilentlyWrapping() {
        // Price large enough that inputTokens * price cannot be
        // represented as a long in units of 1e-5 USD without overflow.
        // We want a hard failure, not a silent negative tally.
        PriceBook.Price price = new PriceBook.Price(new BigDecimal("1000000000"), BigDecimal.ZERO);

        assertThatThrownBy(() -> CostCalculation.compute(price, Long.MAX_VALUE / 2, 0L))
            .isInstanceOf(ArithmeticException.class);
    }

    @Test
    void negativeTokensRejected() {
        assertThatThrownBy(() -> CostCalculation.compute(SONNET, -1L, 0L))
            .isInstanceOf(IllegalArgumentException.class);
    }
}
