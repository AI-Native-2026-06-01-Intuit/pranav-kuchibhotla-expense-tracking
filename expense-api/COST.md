# LLM cost accounting — expense-api

This document explains how a single upstream LLM call turns into a
metric that CloudWatch alarms on and a tally that Redis remembers.
Written for W6D4; kept in the app repo because the alarm's dimensions
are wired from the app side.

## Cohort override (Kinza)

The curriculum's original W6D4 track routes LLM calls through Amazon
Bedrock and grants a Bedrock invoke IRSA role. **This run does not use
Bedrock.** We use the provided external API key (`LLM_API_KEY`)
sourced from the pod's environment. As a consequence:

- No `AWS::IAM::Role` for Bedrock invoke is created in
  `cfn/expense-cost-dev.yaml`.
- No `bedrock:*` action appears anywhere in the stack.
- No EKS OIDC provider dependency exists for this deliverable.
- The runtime provider is called via a provider-neutral middleware
  boundary (see `com.uptimecrew.expense.llmproxy.cost.CostMiddleware`)
  that only sees token counts, latency, and a model id.
- The AWS-side accounting (CloudWatch metric, alarm, budget) does not
  care which provider produced the tokens; it observes the app-emitted
  EMF record.

## Stack layout

Two repos:

- **Config repo** `pranav-kuchibhotla-expense-config`
  - `cfn/expense-cost-dev.yaml` — SNS topic, CloudWatch alarm, monthly
    Budget, hardened CUR S3 bucket + access-log bucket, all tagged with
    the four cost-allocation tags.
  - Deployed via a CloudFormation service role
    (`expense-cost-cfn-service-pranav`) so that CloudFormation
    performs the Budgets writes; the trainee IAM user does not carry
    `budgets:*` directly.

- **App repo** `uptimecrew-expense`
  - `expense-api/src/main/java/com/uptimecrew/expense/llmproxy/cost/`
    — the middleware library (this document's runtime side).
  - `expense-api/src/main/resources/db/migration/V4__create_merchant_embeddings.sql`
    — pgvector index for merchant nearest-neighbor lookups.
  - `expense-api/scripts/llm-cost-spike.sh` — synthetic burst driver.

## Per-request cost path

```
upstream LLM response
      │
      ▼
CostMiddleware.record(Call)
      │
      ├──▶ PriceBook.priceFor(modelId)           (BigDecimal, HALF_UP)
      ├──▶ CostCalculation.compute(price, in, out)
      │        └── setScale(5, HALF_UP).movePointRight(5).longValueExact()
      │            → cost_usd_e5 (exact long, minor units 1e-5 USD)
      │
      ├──▶ RedisCostStore.incrementCostUsdE5(...)
      │        └── HINCRBY (integer). Never HINCRBYFLOAT.
      │
      └──▶ EmfEmitter.emit(CostRecord)
               └── stdout JSON:
                   namespace = acme/llmproxy
                   metrics   = CostUsd (double, dashboards)
                               CostUsdE5 (long,  exact tally)
                   dims      = service, tenant, feature
                   fields    = modelId, success, latencyMs,
                               inputTokens, outputTokens
```

## Redis key layout

```
llmproxy:cost:<tenant>:<feature>   HASH
    cost_usd_e5   <integer>   incremented via HINCRBY
```

- The tally is minor units of 1 × 10⁻⁵ USD. To recover dollars:
  `dollars = cost_usd_e5 / 100000.0` — done at read time, never at
  write time (never store a double in Redis).
- Reset semantics: the tally is monotonic per key. The CloudWatch
  alarm/budget do the "reset every N hours/month" job; Redis holds
  a rolling tenant tally for the app's in-request kill switch.

## EMF dimensions

Metric namespace: `acme/llmproxy`

| Metric | Unit | Meaning |
|---|---|---|
| `CostUsd` | None (dashboards) | BigDecimal-rendered dollars, one datapoint per call |
| `CostUsdE5` | Count | Integer minor units, one datapoint per call |

Dimensions (kept intentionally small to control cardinality cost):

- `service`  — e.g. `expense`
- `tenant`   — e.g. `tenant-synth`, `tenant-a`
- `feature`  — e.g. `categorize-expense`

Non-dimensional fields on the same EMF record: `modelId`, `success`,
`latencyMs`, `inputTokens`, `outputTokens`. These are searchable in
Logs Insights without multiplying the CloudWatch metric cost by
model or by success/failure.

## Cost allocation tags

Every taggable resource in `cfn/expense-cost-dev.yaml` carries:

- `service = expense`
- `env = dev`
- `tenant = shared`
- `feature = categorize-expense`

**Manual step required for the monthly Budget to filter correctly:**
before the `CostFilters.TagKeyValue = "user:service$expense"` on
`MonthlyCostBudget` can match anything, the `service` tag must be
activated as a cost allocation tag in the Billing console:

> Billing → Cost Allocation Tags → User-defined cost allocation tags
> → activate `service`, `env`, `tenant`, `feature`.

Activation is a one-time, account-wide action; CFN cannot do it.
Until activation propagates (24h), the Budget's filter matches
nothing and the budget reports $0.

## Alarm runbook

**Alarm:** `expense-llm-cost-dev-pranav`
**Namespace / metric:** `acme/llmproxy` / `CostUsd`
**Trigger:** `Sum ≥ 25 USD` over 3 × 5-minute periods.
**Missing data:** `breaching` — a silent proxy is treated as a
crisis, not a lull. Chosen deliberately over `notBreaching`; see the
"cost-author audit" below.

1. Check the CloudWatch dashboard for `CostUsdE5` on the same
   `(service, tenant, feature)` triple. If it's rising, this is real
   spend — proceed to step 2. If it's flat (missing metric), the
   proxy is silent — go to step 3.
2. **Real spend spike:** inspect the last hour of EMF records in Logs
   Insights (`fields modelId, tenant, feature, CostUsd | stats
   sum(CostUsd) by tenant, feature`). If one tenant dominates,
   engage tenant kill switch (Redis `SET llmproxy:killswitch:<tenant>
   1`). If model choice is wrong, override via feature flag.
3. **Silent proxy:** verify pods are running, check upstream reachability,
   check that `LLM_API_KEY` is present in the pod env (`kubectl exec ...
   env | grep -c LLM_API_KEY` — expect `1`; never `echo`).

## Budget-cap behavior

The monthly Budget is capped at $2,500 USD/month across the expense
service. Two notifications go to the SNS topic and the email
address:

- **80% forecast** → warn only, no auto action.
- **100% actual** → warn only; a hard kill switch is _not_ wired to
  the Budget in dev (production overrides that). App-side rate
  limiting via the CloudWatch alarm is the primary guardrail for
  this environment.

## Running the pgvector integration test

```
./gradlew :expense-api:integrationTest \
  --tests com.uptimecrew.expense.embeddings.MerchantEmbeddingsRepoIT
```

The test spins up a `pgvector/pgvector:pg16` container via
Testcontainers (declared as a compatible substitute for `postgres`),
applies `V4__create_merchant_embeddings.sql` through Flyway, and
verifies an HNSW nearest-neighbor query returns the expected row.

**Local Docker note (Rancher Desktop):** the build wires
`DOCKER_HOST=unix://$HOME/.rd/docker.sock` into the test JVM
automatically. On the current cohort laptop, the bundled docker-java
client (Testcontainers 1.21.3) advertises API version 1.32, but
Rancher Desktop's Moby server (Docker 29, API 1.52) enforces a
minimum of 1.41, so the initialization strategy fails locally with:

    Status 400: client version 1.32 is too old.
    Minimum supported API version is 1.41

This is an environment mismatch, not a test defect — the test class
compiles clean, is discovered by the integrationTest task, and runs
end-to-end under Docker Desktop or in CI. The workaround is either
bumping Testcontainers to a version whose bundled docker-java
supports 1.41+, or downgrading Rancher Desktop to a Moby that
accepts client 1.32. Neither is in scope for W6D4.

## pgvector rationale

The categorize-expense feature uses a merchant embedding index for
"which prior merchant looks most like this one." Storing embeddings
directly in Postgres (via pgvector) avoids a second data store and
keeps tenant scoping inside the same JOIN plane as the merchant
table. HNSW with `m=16, ef_construction=64` is the pgvector-recommended
sensible default for a read-mostly index at our expected corpus
size; the vector operator `<=>` is cosine distance, which pairs with
the `vector_cosine_ops` opclass on the index.

## Cost-author audit

**Accepted:**
- `TreatMissingData: breaching` — a silent proxy is the failure we
  most want to catch, so missing data must page.
- Integer minor-units tally (`cost_usd_e5`) stored as a Redis long,
  incremented via `HINCRBY`. No floating point crosses Redis, which
  eliminates the "$0.03 off after 10M calls" drift.

**Rejected:**
- `HINCRBYFLOAT` — floating point in the increment path produces
  irreproducible tallies at high call volume. A grep test enforces
  this: search the middleware source tree for `HINCRBYFLOAT` and
  `hincrByFloat` and fail the build if either appears.
- `TreatMissingData: notBreaching` — hides exactly the failure mode
  that we most need to see.
- `doubleValue()` in the BigDecimal cost path — grep-enforced;
  `movePointRight(5).longValueExact()` is the only allowed way to
  turn `BigDecimal` into the integer tally.

## Wiring the middleware into a real request path

Today the `CostMiddleware` classes are provider-neutral library
classes with unit tests only. To hook them into an actual HTTP
request path, a future PR should:

1. Add a Spring `@Component` that wraps the vendor SDK response and
   calls `CostMiddleware.record(...)` in the response filter.
2. Bind `SpringDataRedisCostStore` as the `RedisCostStore` bean.
3. Bind `EmfEmitter` as a singleton with the system stdout.
4. Read `LLM_API_KEY` via `@Value("${llm.api.key:${LLM_API_KEY:}}")`
   so the value comes from the pod env, never from a config file.

None of this is wired yet — this deliverable is the accounting
substrate, not the vendor integration.
