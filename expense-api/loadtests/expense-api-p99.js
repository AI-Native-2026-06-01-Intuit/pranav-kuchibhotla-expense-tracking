// W6D5 load gate for expense-api.
//
// Encodes the three SLO thresholds as hard k6 thresholds so the run
// fails when any budget is exceeded:
//   * p99 latency < 600ms
//   * error rate < 1%
//   * p95 cost per request < $0.004
//
// The cost gate reads the X-Cost-Usd response header emitted by the
// W6D4 LLM cost middleware (see expense-api/COST.md). If the header
// is missing, the request contributes 0 to the trend AND increments a
// counter so a green run with no cost data can still be spotted.
//
// Synthetic-only: tenant tenant-synth. No real tenant IDs; no secrets.

import http from "k6/http";
import { check, sleep } from "k6";
import { Trend, Counter } from "k6/metrics";

// ---- SLO thresholds ----
export const options = {
  thresholds: {
    // p99 latency < 600 ms
    http_req_duration: ["p(99)<600"],
    // error rate < 1%
    http_req_failed: ["rate<0.01"],
    // p95 cost per request < $0.004
    cost_per_request_usd: ["p(95)<0.004"],
  },
  scenarios: {
    steady: {
      executor: "constant-arrival-rate",
      rate: 50,
      timeUnit: "1s",
      duration: "2m",
      preAllocatedVUs: 20,
      maxVUs: 100,
    },
  },
};

// ---- Custom metrics ----
const costPerRequestUsd = new Trend("cost_per_request_usd", true);
const costHeaderMissing = new Counter("cost_header_missing_total");
const synthCalls = new Counter("synth_calls_total");

// ---- Target ----
const TARGET = __ENV.TARGET || "http://127.0.0.1:8080";
const TENANT = "tenant-synth"; // synthetic tenant only; do not change

// ---- Workload mix ----
// Weights are declared explicitly and validated to sum to 1.0 exactly.
// Do NOT let a change silently renormalize the mix - a review that swaps
// 0.7 for 0.6 without touching the others would otherwise be swallowed.
const MIX = [
  { name: "hot_write", weight: 0.7, run: hotWrite },
  { name: "cold_write", weight: 0.2, run: coldWrite },
  { name: "read", weight: 0.1, run: read },
];

function assertMixWeightsSumToOne(mix) {
  const total = mix.reduce((s, e) => s + e.weight, 0);
  // Guard against floating-point drift while still catching real changes.
  if (Math.abs(total - 1.0) > 1e-9) {
    throw new Error(
      `workload mix weights must sum to 1.0, got ${total}: ` +
        JSON.stringify(mix.map((e) => [e.name, e.weight])),
    );
  }
}
assertMixWeightsSumToOne(MIX);

function pickScenario() {
  const r = Math.random();
  let acc = 0;
  for (const entry of MIX) {
    acc += entry.weight;
    if (r <= acc) return entry;
  }
  return MIX[MIX.length - 1];
}

function commonHeaders() {
  return {
    "Content-Type": "application/json",
    "X-Tenant-Id": TENANT,
    "X-Feature": "categorize-expense",
    "X-Synthetic": "true",
  };
}

function recordCost(res) {
  synthCalls.add(1);
  // Real gate: W6D4 cost middleware sets X-Cost-Usd on every LLM-touching
  // response. If it's missing we record 0 to keep the p95 well-defined,
  // but bump a counter so a run with structurally missing headers doesn't
  // look green just because 0 < 0.004.
  const raw = res.headers["X-Cost-Usd"] || res.headers["x-cost-usd"];
  if (raw === undefined) {
    costHeaderMissing.add(1);
    costPerRequestUsd.add(0);
    return;
  }
  const v = Number(raw);
  costPerRequestUsd.add(Number.isFinite(v) ? v : 0);
}

function hotWrite() {
  const body = JSON.stringify({
    tenantId: TENANT,
    merchant: "Starbucks",
    amount: 4.75,
    date: "2026-07-15",
  });
  const res = http.post(`${TARGET}/api/v1/expenses`, body, {
    headers: commonHeaders(),
    tags: { scenario: "hot_write" },
  });
  check(res, { "hot_write status < 500": (r) => r.status < 500 });
  recordCost(res);
}

function coldWrite() {
  const body = JSON.stringify({
    tenantId: TENANT,
    merchant: `Merchant-${Math.floor(Math.random() * 1e6)}`,
    amount: Number((Math.random() * 500).toFixed(2)),
    date: "2026-07-15",
  });
  const res = http.post(`${TARGET}/api/v1/expenses`, body, {
    headers: commonHeaders(),
    tags: { scenario: "cold_write" },
  });
  check(res, { "cold_write status < 500": (r) => r.status < 500 });
  recordCost(res);
}

function read() {
  const res = http.get(`${TARGET}/api/v1/expenses?tenantId=${TENANT}&limit=20`, {
    headers: commonHeaders(),
    tags: { scenario: "read" },
  });
  check(res, { "read status < 500": (r) => r.status < 500 });
  recordCost(res);
}

export default function () {
  pickScenario().run();
  sleep(0.05);
}
