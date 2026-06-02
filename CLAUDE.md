# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project state

Week 1 Day 1 of bootstrapping the expense-tracking domain (see `README.md`). The Gradle scaffold and package layout are in place, but `src/main/java/com/uptimecrew/expense/{model,service}` and the matching test packages are **empty** — no domain code has been written yet. Treat new work as greenfield within the established package layout.

## Build & test

Use the Gradle wrapper (JDK 17+ required; toolchain provisions a matching JDK if the system default differs).

- `./gradlew build` — compile and run tests
- `./gradlew test` — run tests only
- `./gradlew test --tests "com.uptimecrew.expense.model.ExpenseTest"` — single test class
- `./gradlew test --tests "com.uptimecrew.expense.model.ExpenseTest.shouldRejectNegativeAmount"` — single test method
- `./gradlew clean` — wipe `build/`

Test output streams to the console (`showStandardStreams = true` in `build.gradle`), so `System.out` from tests is visible without flags. Testing is **JUnit 5 only** — do not add JUnit 4 dependencies.

## Package layout

Root package: `com.uptimecrew.expense` (mirrored under `src/test/java/...`, same-package so package-private members are reachable from tests).

- `com.uptimecrew.expense.model` — domain entities and value objects
- `com.uptimecrew.expense.service` — domain services and use-case orchestration

## Domain coding rules

These rules are non-negotiable for all model and service code:

**Money**
- `java.math.BigDecimal` only. **Never** `double` or `float` for monetary values.
- Construct with scale 2 and `RoundingMode.HALF_UP` (e.g., `amount.setScale(2, RoundingMode.HALF_UP)`).
- Apply the scale/rounding at construction and after every arithmetic operation that can change scale (`multiply`, `divide`).

**Identifiers**
- IDs are `String` only. **Never** `int`, `long`, or numeric ID types — even for internal entities.

**Dates & times**
- `java.time.LocalDate` for calendar dates (e.g., expense date).
- `java.time.Instant` for timestamps (e.g., createdAt, updatedAt).
- **Forbidden:** `java.util.Date`, `java.sql.Date`, `java.util.Calendar`. Do not import them; do not accept them at API boundaries.

**Class & field shape**
- Classes are `final` by default. Only drop `final` with a deliberate reason (e.g., a sealed hierarchy or a framework that requires subclassing).
- Fields are `private final` by default. Initialize in the constructor.
- **No setters.** Mutation produces a new instance (return `this`-typed copies with the change applied).
- **No Lombok `@Data`.** It generates setters and a mutable-style API that violates the rules above. Other Lombok annotations are not in scope yet — prefer hand-written constructors, accessors, `equals`/`hashCode`, and `toString` for now (Java records are also acceptable for pure value objects, since they're implicitly final and immutable).

## When adding dependencies

No production dependencies are declared yet. Add them under `dependencies { implementation '...' }` in `build.gradle`. Test-only libraries go under `testImplementation`.
