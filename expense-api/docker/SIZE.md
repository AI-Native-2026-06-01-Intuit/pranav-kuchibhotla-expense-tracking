# W5D1 Task 2 — Image Size & Layer Cache Report

## Image size comparison

| Variant | Content size | Notes |
|---|---:|---|
| Single-stage (JDK + Gradle + source + jar) | 629 MB | Temporary baseline; ships JDK, Gradle caches, and source |
| **Three-stage distroless (final)** | **189 MB** | JRE 21 on distroless, layered boot jar, no JDK, no source |

Reduction: **(629 − 189) / 629 ≈ 69.9%**. Well under the 250 MB target.

Measured with `docker image ls uptimecrew/expense-api` — content size column.

## Warm rebuild timing

Measured on branch `w5d1-implementation` with the layered Dockerfile.

| Scenario | Wall time |
|---|---:|
| Fully cached rebuild (no changes) | 1.55 s |
| Source-only change (one comment edit in `MerchantController.java`) | **9.87 s** |

Under the 10-second target. In the source-only rebuild the Gradle dependency
resolution step (`./gradlew --no-daemon dependencies`) reports `CACHED`; the
only work executed is `COPY src` and `bootJar -x test` (7.6 s of the 9.87 s).

## Docker history — final image (`uptimecrew/expense-api:0.1.0`)

Runtime app layers (Dockerfile-owned):

| Layer | Size |
|---|---:|
| `COPY /extract/dependencies/` | **140 MB** |
| `COPY /extract/spring-boot-loader/` | 696 kB |
| `COPY /extract/snapshot-dependencies/` | 4.1 kB (empty; app itself lives in `application/`) |
| `COPY /extract/application/` | **422 kB** |

Distroless base layers (bazel-built):

| Layer | Size |
|---|---:|
| `temurin_jre_21_arm64` (JRE only) | 167 MB |
| `libc6` | 24.1 MB |
| assorted debian12 nonroot bits | < 15 MB combined |

## Verification against rubric

- **No JDK-sized layer in runtime**: confirmed — runtime base is
  `gcr.io/distroless/java21-debian12:nonroot`, which contains JRE 21 only
  (167 MB layer). JDK stays in the discarded builder stage.
- **Largest app-owned layer is dependencies, not application code**:
  confirmed — 140 MB dependencies vs. 422 kB application. Ratio ≈ 340×.
  A source-only rebuild only invalidates the 422 kB layer.
- **No `.java` sources in final image**: confirmed — `layertools extract`
  splits the boot jar into class/resource layers only; sources never leave
  the builder stage.

## How to reproduce

```bash
docker build \
  --build-arg APP_VERSION=0.1.0 \
  --build-arg GIT_SHA=$(git rev-parse --short HEAD) \
  -t uptimecrew/expense-api:0.1.0 ./expense-api

docker image ls uptimecrew/expense-api
docker history uptimecrew/expense-api:0.1.0
```

For the warm-rebuild timing, run the build twice (second run is fully
cached), or touch one `.java` file and time the third build.

## Task 3 scope note — smoke profile deferred

Task 3 verifies **image-level** hardening: non-root user, HEALTHCHECK
directive, no baked secrets, small build context, and the presence of a
cross-architecture (`amd64`/`arm64`) healthcheck binary. All of these are
confirmed via `docker inspect` on the built image and pass without any
external dependencies.

A standalone smoke profile that boots the app *without* Postgres, Mongo,
Redis, and Kafka was intentionally **not** added. The app's bean graph
has hard, constructor-required dependencies on those services (e.g.,
`StringRedisTemplate`, `KafkaTemplate`, `MongoRepository` implementations
consumed by `IdempotencyService`, `OutboxPublisher`, `LlmSummaryService`,
and `MerchantClassifiedListener`). Making the app boot in isolation would
require either app-code changes (adding `@Profile("!smoke")` guards) or
introducing fake beans — both are out of scope for Task 3, which
explicitly forbids modifying application behavior.

Full end-to-end "container becomes healthy" verification is deferred to
W5D2, when Compose-managed backing services and a migrated schema become
available.
