package com.uptimecrew.expense.llmproxy.cost;

import java.util.Objects;

import org.springframework.data.redis.core.StringRedisTemplate;

/**
 * Spring Data Redis adapter for {@link RedisCostStore}. Uses HINCRBY
 * exclusively — the {@code increment(key, hashField, long)} overload
 * on {@code HashOperations} maps to HINCRBY, not HINCRBYFLOAT.
 *
 * We intentionally do not depend on Jedis directly; the existing
 * expense-api build already wires a StringRedisTemplate through
 * spring-boot-starter-data-redis, and reusing it keeps the connection
 * pool and error handling consistent with the rest of the service.
 */
public final class SpringDataRedisCostStore implements RedisCostStore {

    private static final String KEY_PREFIX = "llmproxy:cost:";
    private static final String FIELD = "cost_usd_e5";

    private final StringRedisTemplate redis;

    public SpringDataRedisCostStore(StringRedisTemplate redis) {
        this.redis = Objects.requireNonNull(redis, "redis");
    }

    @Override
    public long incrementCostUsdE5(String tenant, String feature, long deltaE5) {
        String key = keyFor(tenant, feature);
        Long total = redis.opsForHash().increment(key, FIELD, deltaE5);
        return total == null ? 0L : total;
    }

    @Override
    public long readCostUsdE5(String tenant, String feature) {
        String key = keyFor(tenant, feature);
        Object raw = redis.opsForHash().get(key, FIELD);
        if (raw == null) {
            return 0L;
        }
        return Long.parseLong(raw.toString());
    }

    private static String keyFor(String tenant, String feature) {
        Objects.requireNonNull(tenant, "tenant");
        Objects.requireNonNull(feature, "feature");
        return KEY_PREFIX + tenant + ":" + feature;
    }
}
