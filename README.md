# Week 1 Day 1 — Bootstrap the Expense-Tracking Domain

A small domain model for tracking expenses: transactions with amounts,
dates, merchants, and categories; receipts attached to transactions; and
classifiers that infer category or kind from transaction data.

## Package layout

Root package: `com.uptimecrew.expense`

- `com.uptimecrew.expense.model` — domain entities and value objects
- `com.uptimecrew.expense.service` — domain services and classifiers

## Domain types

- `Transaction` — a single expense entry (amount, date, merchant, kind, category)
- `ExpenseCategory` — category assigned to a transaction
- `Receipt` — supporting document attached to a transaction
- `TransactionKind` — kind/type of a transaction
- `TransactionClassifier` — assigns a category to a transaction
- `MerchantNameClassifier` — infers category from the merchant name

## Build & test

Requires JDK 17+. Uses the Gradle wrapper.

- `./gradlew test` — run tests
- `./gradlew build` — compile and run tests
- `./gradlew test --tests "com.uptimecrew.expense.model.ExpenseTest"` — single test class

## Conventions

- Money: `java.math.BigDecimal` (scale 2, `HALF_UP`) — never `double`/`float`
- Identifiers: `String` — never numeric ID types
- Dates: `java.time.LocalDate` for calendar dates, `java.time.Instant` for timestamps
- Tests: JUnit 5 only

## Day 2

Adds a queryable transaction ledger using immutable collection snapshots, stream pipelines, Optional-based lookup, and parameterized JUnit 5 tests.

## Day 3

Adds multiple transaction-classification strategies, a factory for choosing them, constructor-injected classification service behavior, record-based model code, and Mockito-backed service tests.

## Day 4

Adds typed expense-classification exceptions, SLF4J/Logback service logging, AssertJ exception assertions, and Logback ListAppender tests.

## Day 5

Adds a TDD-built recurring-charge classifier, a Transaction test data builder, JaCoCo coverage reporting, and a prompt journal.

## Week 2 Day 1

Adds Postgres schema, transactional seed, verification SQL, and database README for expense classification persistence.

## Week 2 Day 2

Adds advanced SQL query files (`db/queries/*.sql`: joins, CTE, window, GROUP BY + HAVING) and a Testcontainers-backed `MerchantQueryIT` that applies the schema + seed and validates the queries against a real Postgres 16 container.

## Week 2 Day 3

Bootstraps Spring Boot (`Application`, `@SpringBootApplication`), promotes `ExpenseClassificationService` to a Spring-managed `@Service` with `MerchantNameClassifier` as the `@Primary` `@Component`, adds a profile-aware `application.yml` (local/test) wiring Hikari + Postgres datasource and exposing Actuator `health`/`info`, and adds an `@SpringBootTest`-driven `ApplicationContextLoadIT` to verify the context loads and the primary classification strategy is wired.

## Week 2 Day 4

Adds Spring Data JPA: maps the W2D1 schema to `Merchant`/`MerchantTransaction`/`Rule` entities under `com.uptimecrew.expense.entity`, adds Spring Data repositories (`MerchantRepository`, `MerchantTransactionRepository`, `RuleRepository`) with derived queries and `@Query` JPQL, wires `MerchantRepository` into `ExpenseClassificationService` so a `@Transactional classify(...)` persists a `Merchant` after a successful classification, and adds a `@DataJpaTest` `MerchantRepositoryIT` backed by a real Postgres 16 container via Testcontainers + `@ServiceConnection`.

## Week 2 Day 5

Adds a MongoDB `MerchantReadModel` (and Spring Data Mongo repository), a Redis-backed `@Cacheable` read path (`ExpenseClassificationService.findById`) gated by `@EnableCaching`, write-through from `ExpenseClassificationService.classify(...)` to the Mongo read model after the JPA save succeeds, and a polyglot `MerchantPolyglotIT` integration test driving real Postgres, MongoDB, and Redis containers via Testcontainers + `@ServiceConnection`.

## Week 3 Day 1

Adds Spring Security 7 Resource Server JWT protection (`SecurityConfig` with a single `SecurityFilterChain`, stateless sessions, `@EnableMethodSecurity`), a JWT authority mapper that combines the standard `scope` claim (`SCOPE_*`) with a custom `roles` claim (`ROLE_*`), a `@PreAuthorize`-guarded `MerchantController` exposing `GET /api/merchants/{id}` over the W2D5 cached read path, a Bucket4j-backed `RateLimitFilter` enforcing 10 req/min per JWT subject on the LLM `GET /api/merchants/{id}/summary` stub endpoint (429 + `Retry-After: 60`), and a `MerchantSecurityIT` covering the full security matrix (200 / 401 / 403 / 429) against real Postgres, MongoDB, and Redis Testcontainers via `@ServiceConnection`.

## Week 3 Day 2

Versions the merchant API under `/api/v1/merchants` with springdoc OpenAPI 3.1 docs (`OpenApiConfig` exposing a `bearer-jwt` HTTP/JWT security scheme at `/v3/api-docs` and `/swagger-ui.html`), converts the LLM summary route to `POST /api/v1/merchants/{id}/summary` with Redis-backed `Idempotency-Key` semantics (`IdempotencyService` using a `__in_flight__` SETNX sentinel + 24h TTL, 400 on missing/invalid UUID, 409 on replay-in-flight), introduces a Spring Cloud OpenFeign `MerchantIdentityClient` wrapped by an `IdentityService` whose `getProfile` is protected by a Resilience4j `@CircuitBreaker(name = "identity")` with a degraded-profile fallback (configured in `application.yml`), enriches the summary response with the caller's `displayName` from identity, and adds a WireMock-backed `IdentityClientCircuitBreakerIT` (port 8090) that covers identity 200 happy-path decoding, breaker-opens-after-5xx with fallback + no further upstream calls, the end-to-end summary POST returning the identity displayName, and an OpenAPI assertion that `/v3/api-docs` exposes `/api/v1/merchants/{id}` and the `bearer-jwt` scheme.

## Week 3 Day 4

Adds a Spring for GraphQL endpoint at `/graphql` (with GraphiQL at `/graphiql`) backed by `src/main/resources/graphql/schema.graphqls` exposing `merchant(id)`, `latestMerchants(limit)`, and `summarizeMerchant(id)`; implements the resolvers in `MerchantGraphQlController` with an `@BatchMapping(typeName = "Merchant", field = "lines")` that resolves all parents in one pass over the Mongo read model (no N+1); wires Spring AI Anthropic so `LlmSummaryService.summarize(id)` produces a `MerchantSummary` via `chatClient.prompt().user(...).call().entity(MerchantSummary.class)` and then re-validates the candidate against a hand-written JSON Schema 2020-12 at `src/main/resources/schemas/MerchantSummary.schema.json` (networknt `JsonSchemaFactory`, `additionalProperties: false`, all four fields required); and adds `MerchantGraphQlIT` (Testcontainers Postgres/Mongo/Redis, `@MockitoBean LlmSummaryService` so no real Anthropic call) covering the seeded `merchant(id)` query, the `latestMerchants(limit:5)` batch-mapping `lines` resolution, and the `summarizeMerchant` mutation re-validated against the same JSON Schema. Verify with `./gradlew clean check` — passes under Rancher Desktop with `DOCKER_HOST=unix:///$HOME/.rd/docker.sock` and `TESTCONTAINERS_RYUK_DISABLED=true`.

## Week 3 Day 5

Adds OpenTelemetry bootstrap (`opentelemetry-spring-boot-starter`, OTLP exporter, spring-kafka instrumentation) configured under `otel.*` in `application.yml`, with the test profile defensively setting `otel.traces.exporter=none` / `sampler=always_off` / spring-kafka+kafka instrumentation `enabled=false` so existing ITs don't need a collector. Adds a Kafka `TraceparentLoggingProducerListener` (`@Component` declared as `ProducerListener<Object, Object>` so it satisfies the raw injection point Spring Boot's `KafkaAutoConfiguration` uses, avoiding the generic-mismatch "no qualifying bean" failure that `<String, String>` triggers) — logs `traceparent=<value> topic=<t> key=<k>` on success, warns if the header is missing. Wraps the Spring AI `ChatClient` call in `LlmSummaryService` in a manual `llm.summarize` CLIENT span with attributes `llm.model`, `llm.input.aggregate_id`, `llm.tokens.in`, `llm.tokens.out` (Spring AI usage metadata, defaulting to `0L` when absent), `recordException` + `setStatus(ERROR, simpleName)` on failure and `setStatus(OK)` on success, always ended in `finally`. Adds `MerchantObservabilityIT` with an `InMemorySpanExporter` wired via `SimpleSpanProcessor` plus a `W3CTraceContextPropagator` (so traceparent headers actually get injected) and a `@Primary OpenTelemetry` test bean overriding the autoconfigured SDK: asserts an HTTP `SERVER` span shares its trace id with a JDBC span on `GET /api/v1/merchants/{id}`, asserts an end-to-end Kafka write-through emits PRODUCER/CONSUMER/JDBC/Mongo spans on `merchants.events` with at least one consumer span sharing a trace id with a producer span (loose, because scheduler-driven outbox dispatches each start a fresh root trace), and asserts the `llm.summarize` span carries non-blank `llm.model`, the exact `llm.input.aggregate_id`, and non-null `llm.tokens.in`/`llm.tokens.out`. Adds a small derived GraphQL field `Merchant.observabilityLabel: String!` resolved by `@SchemaMapping` as `merchant:<id>:mcc:<mccCode-or-unknown>` (treats null/blank `mccCode` as `unknown`) with a deterministic `MerchantGraphQlIT` assertion against the seeded `5812` mcc. Verify with `./gradlew test --tests "*MerchantObservabilityIT"` and then `./gradlew clean check` — passes under Rancher Desktop with `DOCKER_HOST="unix://$HOME/.rd/docker.sock"`, `TESTCONTAINERS_DOCKER_SOCKET_OVERRIDE=/var/run/docker.sock`, and `JAVA_TOOL_OPTIONS="-Dapi.version=1.41 -Ddocker.api.version=1.41"`.

## Prompt Journal

### Entry 1

- **Prompt:** "Create only the failing RecurringChargeClassifierTest first. Do not create the production class yet. Use AssertJ, AAA comments, @DisplayName, and four behavior tests."
- **What it suggested:** Claude generated the first test draft and flagged that a blank merchant test could not work because the Transaction record already rejects blank merchant names before the classifier can receive the transaction.
- **What I accepted or rejected and why:** I accepted the warning and rejected the original blank-merchant classifier test. The test would have asserted behavior that could never be reached because Transaction validation fails first. I replaced it with `constructor_nullHistory_throwsNullPointerException`, which still covers invalid input and matches the classifier constructor contract.

### Entry 2

- **Prompt:** "Create RecurringChargeClassifier with only enough production code to make the existing tests pass."
- **What it suggested:** Claude suggested a final classifier implementing TransactionClassifier, defensively copying history, filtering same-merchant transactions, checking monthly cadence, and checking amount stability.
- **What I accepted or rejected and why:** I accepted the simple implementation because it matched the tests and kept the Red-Green step focused. I avoided adding factory wiring or unrelated production behavior because those changes were not required by the failing tests.

### Entry 3

- **Prompt:** "JaCoCo check is failing below the 70% branch threshold. Add focused branch-coverage tests without lowering the threshold."
- **What it suggested:** Claude suggested adding tests for non-monthly cadence, null transaction, empty history, and cadence edge cases.
- **What I accepted or rejected and why:** I accepted adding behavior-focused tests because they covered real classifier branches and helped the build pass the JaCoCo gate. I rejected lowering the JaCoCo threshold because the assignment explicitly requires a 70% branch coverage gate.
