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

### Week 3 Day 5 — 3-agent workflow (Task 5)

The small W3D5 feature (GraphQL `Merchant.observabilityLabel: String!` resolving to `merchant:<id>:mcc:<mccCode-or-unknown>`) was driven by a three-agent flow:

- **Generator** — *Prompt:* derive a stable read-only label from `MerchantReadModel` for traces/logs, exposed as a non-null GraphQL field, no migrations, no write-path changes. *Output:* `observabilityLabel: String!` added to `type Merchant` in `schema.graphqls`, and a `@SchemaMapping(typeName="Merchant", field="observabilityLabel")` resolver in `MerchantGraphQlController` that concatenates `"merchant:" + id + ":mcc:" + safeMcc`.
- **Tester** — *Prompt:* prove the field returns the exact label for the existing seeded data without weakening the assertion. *Output:* `query_merchant_observabilityLabel_matchesSeededMcc()` in `MerchantGraphQlIT` documenting `merchant(id: "seeded-id-1") { observabilityLabel }` and asserting `.isEqualTo("merchant:seeded-id-1:mcc:5812")` against the seeded `5812` mcc.
- **Reviewer** — *Prompt:* check null/blank handling, GraphQL non-null contract, and test brittleness. *Concrete change request:* the initial resolver only checked `mcc == null`; the spec says null **or blank**, so an empty/whitespace mccCode would have produced a malformed `merchant:abc:mcc:` label. *Addressed:* tightened the guard to `(mcc == null || mcc.isBlank()) ? "unknown" : mcc` before commit; the `String!` contract holds because `merchant.getId()` is the loaded document's `@Id` and the mcc branch always picks a non-empty value.

## Week 4 Day 1

Adds a new top-level `expense-web/` frontend scaffold: React 19 + Vite + TypeScript with strict guardrails (`strict`, `noUncheckedIndexedAccess`, `exactOptionalPropertyTypes`, `verbatimModuleSyntax`, `noImplicitOverride`, plus the usual `noUnused*`/`isolatedModules` set) and an ESLint 9 flat config (`@eslint/js` + `typescript-eslint` `recommendedTypeChecked` scoped to `**/*.{ts,tsx}`, `eslint-plugin-react`, `react-hooks`, `react-refresh`; rules include `@typescript-eslint/no-explicit-any: error` and `no-floating-promises: error`). Wires a stubbed merchant read model at `public/mocks/merchant.json` consumed by a `useMerchant(id)` hook that fetches, parses, and narrows the payload through a hand-written `isMerchant` type guard before exposing a discriminated-union `loading | ok | error` state (flattened to `{ data, loading, error }` at the return boundary, with a `cancelled` cleanup flag). Adds `MerchantDetailPage` mounted at the hash route `#/merchants/stub-id-1` that owns a lifted `threshold` state and feeds it to two siblings — a keyboard-accessible controlled `ThresholdSlider` (`<input type="range">` with an explicit `onKeyDown` handler for ArrowLeft/Right/Up/Down/Home/End, `preventDefault` + clamped 0–100 updates, deterministic in jsdom and browsers) and a `ThresholdReadout` with `role="status"`. Adds Vitest + React Testing Library smoke tests (`MerchantDetailPage.test.tsx`) covering the stubbed-fetch render (heading + mccCode) and the lifted-state interaction (`userEvent.keyboard('{ArrowRight}')` advances the readout to `Threshold: 51%`), wired via `vitest.config.ts` (jsdom, globals, `setupFiles: ['./src/test/setup.ts']` importing `@testing-library/jest-dom`). Adds `.github/workflows/web-ci.yml` — a PR-gated job triggered on `expense-web/**` and the workflow file itself, running `npm ci` → `npm run lint` → `npm run typecheck` → `npm test` → `npm run build` on Node 20 with the npm cache keyed to `expense-web/package-lock.json`. npm is used throughout (not pnpm) because pnpm and corepack are unavailable on the local machine; the assignment allows npm 10+, and this machine has npm 11.12.1.

## Week 4 Day 3

Layers Apollo Client, TanStack Query v5, React Router v7, and MSW onto the W4D1/W4D2 `expense-web/` scaffold. Bootstraps an `ApolloClient` (`expense-web/src/apollo/client.ts`) with an `HttpLink` pointed at `http://localhost:8080/graphql`, a `setContext` auth link that reads the JWT from `localStorage` under the `uc:jwt` key and attaches it as `authorization: Bearer ${token}` when present, `link: from([authLink, httpLink])`, and an `InMemoryCache` with `typePolicies: { Merchant: { keyFields: ['id'] } }`. A threat-model comment documents that JWT-in-localStorage is XSS-exposed and accepted only as a stopgap until an HttpOnly cookie flow lands. Wires GraphQL Codegen with the client-preset (`expense-web/codegen.ts`, scripts `codegen` / `codegen:watch`); because the live Spring for GraphQL backend doesn't yet expose `latestMerchants` / `summarizeMerchant`, an offline `expense-web/schema.graphql` fallback is used (`UC_CODEGEN_OFFLINE=1 npm run codegen`) and emits artifacts under `expense-web/src/gql/generated/` (`graphql.ts`, `gql.ts`, `index.ts`, `fragment-masking.ts`). Adds `src/queries/LatestMerchants.graphql` (`latestMerchants(limit: 20) { id name updatedAt __typename }`) consumed by `MerchantListPage` via `useQuery(LatestMerchantsDocument)` with `loading → role="status"`, `error → role="alert"`, empty → `"No merchants yet."`, and a populated `<ul aria-label="merchant-list">`. Adds `src/queries/SummarizeMerchant.graphql` (`summarizeMerchant(id: ID!) { id summaryText confidence __typename }`) consumed by `MerchantSummaryPage` via `useMutation` with an `optimisticResponse` of `{ summarizeMerchant: { __typename: 'MerchantSummary', id, summaryText: '...thinking...', confidence: 'MEDIUM' } }` and a summary card that renders the optimistic placeholder while the mutation is in flight and then the real `MerchantSummary` payload. Adds a shared TanStack `QueryClient` (`src/queryClient.ts`) with `staleTime: 60_000`, `refetchOnWindowFocus: false`, `retry: 1`, and a `useGetExpenseTrackingRest(id: string)` hook (`src/hooks/useGetExpenseTrackingRest.ts`) that uses `queryKey: ['expense', id]`, `enabled: Boolean(id)`, fetches `http://localhost:8080/api/v1/merchants/${id}`, throws `HTTP ${status}` on a non-ok response, and returns a typed `MerchantRest`. Adds React Router v7 via `createBrowserRouter` (`src/router.tsx`) with routes `/login → LoginPage`, `/ → Navigate('/merchants')`, `/merchants → MerchantListPage`, `/merchants/:id → MerchantDetailPage`, `/merchants/:id/summary → MerchantSummaryPage` — the merchant routes are nested under a `ProtectedLayout` that reads `localStorage.getItem('uc:jwt')` and returns `<Navigate to="/login" replace />` when missing, otherwise `<Outlet />`. `LoginPage` is a stub sign-in: a button writes a fake JWT to `uc:jwt` and `navigate('/merchants')`. `main.tsx` mounts the chain `StrictMode → ApolloProvider → QueryClientProvider → RouterProvider`. Also factors out `routes: RouteObject[]` and exports `createAppRouter(initialEntries)` so tests can drive the router with `createMemoryRouter`. Adds MSW v2 handlers (`src/test/handlers.ts`): `graphql.query('LatestMerchants', ...)` returns three Merchants (`stub-1`/`stub-2`/`stub-3` with `__typename: 'Merchant'`), `graphql.mutation('SummarizeMerchant', ...)` returns a `MerchantSummary` echoing `variables.id` with `summaryText: 'stub summary from MSW'` and `confidence: 'HIGH'` (with a small `delay(50)` so the optimistic placeholder is observable), and `http.get('http://localhost:8080/api/v1/merchants/:id', ...)` returns `{ id, name: 'stub merchant', updatedAt: '2025-01-04T00:00:00Z' }`. `src/test/server.ts` wires `setupServer(...handlers)` with `beforeAll(server.listen({ onUnhandledRequest: 'error' }))`, `afterEach(server.resetHandlers())`, `afterAll(server.close())`, and `src/test/setup.ts` imports `./server`. Vitest's environment is switched from `jsdom` to `happy-dom` because jsdom's polyfilled `AbortController` does not pass undici's `instanceof` check when MSW intercepts on Node 26. Adds four new test files — `MerchantListPage.test.tsx` (three list items render; "stub one" is visible), `MerchantSummaryPage.test.tsx` (Summarize click shows optimistic `...thinking...` then real `stub summary from MSW`; heading reflects the route-param id), `ProtectedLayout.test.tsx` (no JWT → redirect to `/login`; with JWT → the protected child renders), and `useGetExpenseTrackingRest.test.tsx` (success returns `name: 'stub merchant'`; empty id keeps the query idle via the `enabled` gate). W4D1 and W4D2 tests continue to pass; total test count is **21** across 8 files. npm is used throughout (not pnpm) because pnpm and corepack are unavailable on the local machine.

### Week 4 Day 3 — AI Tool Reflection

- **Accepted:** Accepted Claude's suggestion to keep server state in Apollo and TanStack Query instead of copying it into Zustand. Server data belongs in query caches that already handle staleness, retries, and cache keys; Zustand stays focused on UI-only filter state, which keeps the two layers cleanly separated and avoids hand-rolled cache invalidation.
- **Rejected:** Rejected the shortcut of dropping the JWT into `localStorage` with no explanation. localStorage was kept because the assignment requires it, but a threat-model comment was added in `src/apollo/client.ts` and `src/router.tsx` documenting that storing a JWT there is XSS-exposed and accepted only until an HttpOnly cookie auth flow exists.

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
