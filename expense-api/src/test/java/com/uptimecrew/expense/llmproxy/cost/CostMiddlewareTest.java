package com.uptimecrew.expense.llmproxy.cost;

import static org.assertj.core.api.Assertions.assertThat;

import java.io.ByteArrayOutputStream;
import java.io.PrintStream;
import java.math.BigDecimal;
import java.nio.charset.StandardCharsets;
import java.time.Clock;
import java.time.Instant;
import java.time.ZoneOffset;
import java.util.HashMap;
import java.util.Map;

import org.junit.jupiter.api.Test;

class CostMiddlewareTest {

    @Test
    void recordIncrementsTallyAndEmitsEmf() throws Exception {
        FakeRedisCostStore store = new FakeRedisCostStore();
        ByteArrayOutputStream buf = new ByteArrayOutputStream();
        EmfEmitter emitter = new EmfEmitter(
            new PrintStream(buf, true, StandardCharsets.UTF_8),
            Clock.fixed(Instant.EPOCH, ZoneOffset.UTC)
        );

        CostMiddleware mw = new CostMiddleware(PriceBook.defaults(), store, emitter);

        CostRecord first = mw.record(new CostMiddleware.Call(
            "expense",
            "tenant-synth",
            "categorize-expense",
            "claude-sonnet-4-5",
            1_000L,
            0L,
            10L,
            true
        ));

        CostRecord second = mw.record(new CostMiddleware.Call(
            "expense",
            "tenant-synth",
            "categorize-expense",
            "claude-sonnet-4-5",
            0L,
            1_000L,
            12L,
            true
        ));

        assertThat(first.costUsdE5()).isEqualTo(300L);
        assertThat(second.costUsdE5()).isEqualTo(1_500L);

        // Cumulative tally is 300 + 1500 = 1800 (integer HINCRBY, not float).
        assertThat(store.readCostUsdE5("tenant-synth", "categorize-expense")).isEqualTo(1_800L);

        String[] lines = buf.toString(StandardCharsets.UTF_8).trim().split("\\R");
        assertThat(lines).hasSize(2);
        assertThat(lines[0]).contains("\"CostUsdE5\":300");
        assertThat(lines[1]).contains("\"CostUsdE5\":1500");
    }

    @Test
    void unknownModelRejectedBeforeAnyRedisWrite() {
        FakeRedisCostStore store = new FakeRedisCostStore();
        EmfEmitter emitter = new EmfEmitter(new PrintStream(new ByteArrayOutputStream()), Clock.systemUTC());
        CostMiddleware mw = new CostMiddleware(PriceBook.defaults(), store, emitter);

        try {
            mw.record(new CostMiddleware.Call(
                "expense", "tenant-synth", "categorize-expense",
                "unknown-model", 100L, 100L, 1L, true));
        } catch (IllegalArgumentException expected) {
            // no-op
        } catch (Exception unexpected) {
            throw new AssertionError("unexpected exception type", unexpected);
        }

        assertThat(store.incrementCalls).isZero();
    }

    /**
     * Deterministic in-memory HINCRBY simulator. Not a mock — exercising
     * the actual integer-add semantics we rely on in production, so
     * refactors to the store adapter can't silently regress to
     * HINCRBYFLOAT-style behavior.
     */
    static final class FakeRedisCostStore implements RedisCostStore {
        final Map<String, Long> data = new HashMap<>();
        int incrementCalls = 0;

        @Override
        public long incrementCostUsdE5(String tenant, String feature, long deltaE5) {
            incrementCalls++;
            String key = tenant + ":" + feature;
            long updated = data.getOrDefault(key, 0L) + deltaE5;
            data.put(key, updated);
            return updated;
        }

        @Override
        public long readCostUsdE5(String tenant, String feature) {
            return data.getOrDefault(tenant + ":" + feature, 0L);
        }
    }
}
