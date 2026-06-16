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
