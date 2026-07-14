package com.uptimecrew.expense.llmproxy.cost;

/**
 * Integer-only cost tally in Redis, keyed by (tenant, feature).
 *
 * The tally is stored in units of 1e-5 USD ("cost_usd_e5") as a Redis
 * hash field. Incrementing uses HINCRBY (integer). HINCRBYFLOAT is
 * banned — see the cost-author audit in COST.md. A separate rule and
 * a grep test guard against reintroduction.
 */
public interface RedisCostStore {

    /**
     * Adds {@code deltaE5} to the tenant+feature tally and returns the
     * new total, in units of 1e-5 USD. Backed by HINCRBY.
     */
    long incrementCostUsdE5(String tenant, String feature, long deltaE5);

    /** Reads the current tally for a (tenant, feature) key. Returns 0 if absent. */
    long readCostUsdE5(String tenant, String feature);
}
