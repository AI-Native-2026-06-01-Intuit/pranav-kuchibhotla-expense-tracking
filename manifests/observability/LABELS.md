# Loki label discipline for expense-api

Loki indexes on labels only — every distinct label value combination is its
own stream. High-cardinality labels (per-user, per-request, per-merchant IDs)
turn every log line into a new stream, blow up the index, and make queries
slow or run out of memory. Log message *body* is not indexed and is the right
place for identifiers.

## Permitted Loki labels

Use these — they are bounded low-cardinality values:

| Label   | Values                                    | Source                                    |
|---------|-------------------------------------------|-------------------------------------------|
| `app`   | `expense-api`                             | LogstashEncoder `customFields`            |
| `env`   | `k8s`                                     | LogstashEncoder `customFields`            |
| `level` | `TRACE`, `DEBUG`, `INFO`, `WARN`, `ERROR` | Standard Logback                          |
| `pod`   | one per pod, bounded by replica count     | Promtail/Alloy pod discovery              |

## Forbidden as labels

These belong in the log message body only, never as Loki labels:

- `merchantId`     — unbounded (one per merchant, potentially millions)
- `correlationId`  — unbounded (one per request)
- `userId`         — unbounded (one per user)
- `traceId` / `spanId` — extracted from the JSON body via MDC; do not label

## How this is enforced

- `logback-spring.xml` in the `k8s`/`prod` profile ships JSON via
  `LogstashEncoder` with `customFields={"app":"expense-api","env":"k8s"}`
  and includes `trace_id`, `span_id`, and `correlationId` as MDC keys — MDC
  keys become JSON fields, not Loki labels.
- The Promtail/Alloy config that ships these logs to Loki must not extract
  MDC fields into labels. Use `stage` blocks to parse JSON into the
  structured metadata / body only.
- The Grafana RED dashboard and the Sloth-generated PrometheusRule query
  Prometheus by `route`, `status`, `method` only. No metric ever carries an
  ID label — see `ExpenseClassificationService.deductionCounters` (bounded
  to `merchant_type` and `outcome`).
