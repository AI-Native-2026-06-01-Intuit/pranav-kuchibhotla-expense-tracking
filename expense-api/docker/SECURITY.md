# expense-api — Image Security Posture (W5D1 Task 4)

## Base images (pinned by digest)

Digests are the sole source of truth for base-image identity. Tags shift under
you; digests do not. All three FROMs in `expense-api/Dockerfile` are pinned:

| Stage      | Image                                          | Digest |
|------------|------------------------------------------------|--------|
| builder    | `eclipse-temurin:21-jdk-jammy`                 | `sha256:801b7e1a9c4befaf82bf9a2a58025ef43a7694bbc84779187ad0524d84742772` |
| extractor  | `eclipse-temurin:21-jre-jammy`                 | `sha256:199aebeb3adcde4910695cdebfe782ada38dadb6cc8013159b58d3724451befd` |
| runtime    | `gcr.io/distroless/java21-debian12:nonroot`    | `sha256:7e37784d94dccbf5ccb195c73b295f5ad00cd266512dfbac12eb9c3c28f8077d` |

Digests captured 2026-07-01. To refresh:

```bash
docker pull eclipse-temurin:21-jdk-jammy
docker pull eclipse-temurin:21-jre-jammy
docker pull gcr.io/distroless/java21-debian12:nonroot
docker image inspect eclipse-temurin:21-jdk-jammy         --format '{{index .RepoDigests 0}}'
docker image inspect eclipse-temurin:21-jre-jammy         --format '{{index .RepoDigests 0}}'
docker image inspect gcr.io/distroless/java21-debian12:nonroot --format '{{index .RepoDigests 0}}'
```

## Standard commands

Build:
```bash
docker build \
  --build-arg APP_VERSION=0.1.0 \
  --build-arg GIT_SHA=$(git rev-parse --short HEAD) \
  -t uptimecrew/expense-api:0.1.0 ./expense-api
```

Lint:
```bash
hadolint expense-api/Dockerfile --config expense-api/.hadolint.yaml
```

Scan (HIGH/CRITICAL, unfixed excluded, waivers applied):
```bash
trivy image \
  --severity HIGH,CRITICAL \
  --ignore-unfixed \
  --ignorefile expense-api/.trivyignore \
  uptimecrew/expense-api:0.1.0
```

Run (standalone; app will fail readiness without backing services — see
"Readiness smoke scope" below):
```bash
docker run --rm -p 8080:8080 uptimecrew/expense-api:0.1.0
```

Verify image contract:
```bash
docker image ls uptimecrew/expense-api
docker inspect --format '{{.Config.User}}'            uptimecrew/expense-api:0.1.0
docker inspect --format '{{.Config.Healthcheck.Test}}' uptimecrew/expense-api:0.1.0
```

Expected: `User=65532`, healthcheck test contains `/home/nonroot/healthcheck`,
content size < 250 MB (currently 191 MB).

## Scan cadence

- **Every PR touching `expense-api/**` or `.github/workflows/docker.yml`** —
  `hadolint` (fails on ≥ warning) and `trivy` (fails on any new HIGH/CRITICAL
  fixed-in-upstream finding not covered by `expense-api/.trivyignore`) run in
  `.github/workflows/docker.yml`.
- **Every push to `main` under those paths** — same gate re-runs on the merged
  tree.
- **Monthly (out-of-band, first business day)** — rebase all three base-image
  digests to the current upstream and re-scan. This is the mechanism that
  closes waived OS-package findings; missing a month is fine because the next
  PR under those paths re-scans against the current Trivy DB.

## GHCR fallback tagging policy

- **Local/dev canonical tag:** `uptimecrew/expense-api:<APP_VERSION>` (no
  registry prefix; not intended for push).
- **Private-push target:** `ghcr.io/pranav-kuchibhotla/expense-api:<APP_VERSION>`.
- **Tags are immutable.** A published `:X.Y.Z` tag must never be re-pushed
  with a different digest. Republish under a bumped patch (`:X.Y.Z+1`).
- **Deploys pin by digest, not tag.** After push, resolve the digest with
  `docker image inspect ... --format '{{index .RepoDigests 0}}'` and pin the
  deploy manifest to `ghcr.io/pranav-kuchibhotla/expense-api@sha256:<digest>`.
- **The PR workflow never pushes.** `docker/build-push-action@v6` runs with
  `load: true` (into the runner's local daemon, for scan + smoke) and does
  not authenticate to any registry. Publishing is an operator step, gated on
  a manual review outside of CI.

## Operator: push to GHCR (private)

Do **not** commit the PAT anywhere. Use a classic PAT scoped to
`write:packages` and read it from a shell env var / secrets manager on the
operator's machine.

```bash
echo "$GHCR_PAT" | docker login ghcr.io -u Pranav-Kuchibhotla --password-stdin

docker tag uptimecrew/expense-api:0.1.0 ghcr.io/pranav-kuchibhotla/expense-api:0.1.0
docker push ghcr.io/pranav-kuchibhotla/expense-api:0.1.0

# Capture the pushed digest and record it in the deploy manifest.
docker image inspect ghcr.io/pranav-kuchibhotla/expense-api:0.1.0 \
  --format '{{index .RepoDigests 0}}'
```

## Cross-arch healthcheck binary

The distroless runtime ships no shell, no curl, no wget, so Docker's
HEALTHCHECK needs a self-contained executable. `expense-api/docker/healthcheck.go`
is a ~40-line Go program that does a single GET against
`http://127.0.0.1:8080/actuator/health/readiness` and exits 0 iff the response
is 2xx.

Two prebuilt static binaries are committed alongside the source so the
runtime image does not need a Go build stage:

- `expense-api/docker/healthcheck-arm64` — Rancher Desktop / aarch64 dev
- `expense-api/docker/healthcheck-amd64` — GitHub Actions ubuntu-latest

The Dockerfile picks the right one at build time via BuildKit's `TARGETARCH`
build-arg (`COPY docker/healthcheck-${TARGETARCH} /home/nonroot/healthcheck`).

Rebuild (both arches) with a current Go toolchain when a Go stdlib CVE is
disclosed:

```bash
cd expense-api/docker
docker run --rm -v "$PWD":/src -w /src golang:1.26.4-alpine sh -c '
  CGO_ENABLED=0 GOOS=linux GOARCH=arm64 go build -trimpath -ldflags="-s -w" -o healthcheck-arm64 healthcheck.go &&
  CGO_ENABLED=0 GOOS=linux GOARCH=amd64 go build -trimpath -ldflags="-s -w" -o healthcheck-amd64 healthcheck.go
'
```

## Readiness smoke scope

The container reaches `/actuator/health/readiness` only when Postgres,
MongoDB, Redis, and Kafka are reachable and the W2D1 schema is applied. This
is a deliberate consequence of the existing bean graph — `StringRedisTemplate`,
`KafkaTemplate`, and the Mongo/JPA repositories are constructor dependencies
of `IdempotencyService`, `OutboxPublisher`, `LlmSummaryService`, and
`MerchantClassifiedListener`.

The W5D1 CI smoke therefore verifies the **image-level** contract only:

1. `Config.User == 65532` (non-root),
2. `Config.Healthcheck.Test` includes `/home/nonroot/healthcheck`,
3. `docker run -d` launches the container binary on the CI arch (amd64) and
   prints startup logs.

A full `curl` readiness smoke against the running container is scheduled for
**W5D2**, once Compose brings up the backing services and applies the
schema. A "smoke-only" fake profile that would let the app boot in
isolation was intentionally **not** added — it would require app-behavior
changes (`@Profile("!smoke")` guards or fake beans), which the assignment
forbids.

## Waivers (dated)

The CI Trivy gate uses `--ignorefile expense-api/.trivyignore`. Every waived
CVE below has a scheduled review date. **New** HIGH/CRITICAL findings still
fail the gate.

- **Recorded:** 2026-07-01
- **Next review:** 2026-08-01
- **Owner:** Pranav Kuchibhotla (pranav_kuchibhotla@intuit.com)

### Spring Boot BOM & transitive dependencies (31 CVEs)

**Remediation:** Spring Boot `3.5.7 → 3.5.14` BOM bump (patch), plus a
handful of individual libs (bouncycastle → `1.80.2`, lz4-java → `1.8.1`,
commons-fileupload → `1.6.0`, postgres JDBC → `42.7.11`, spring-ai → `1.0.7`,
kafka-clients → `3.9.2`).

**Why deferred:** doing the bump in W5D1 would change application behavior
surfaces (Tomcat, spring-security, Netty request handling) without a
covering integration run. W5D2 brings up the Testcontainers matrix
(Postgres + Mongo + Redis + Kafka) under Compose; the BOM bump will land
there so it can be validated end-to-end before merge.

| Package | Waived CVEs | Fixed in |
|---|---|---|
| `com.fasterxml.jackson.core:jackson-databind` | `CVE-2026-54512`, `CVE-2026-54513` | 2.18.8 / 2.21.4 |
| `commons-fileupload:commons-fileupload` | `CVE-2025-48976` | 1.6.0 |
| `io.netty:netty-codec` | `CVE-2026-42583` | 4.1.133.Final |
| `io.netty:netty-codec-dns` | `CVE-2026-42579` | 4.1.133.Final |
| `io.netty:netty-codec-http` | `CVE-2026-33870`, `CVE-2026-42584`, `CVE-2026-42587` | 4.1.132–133.Final |
| `io.netty:netty-codec-http2` | `CVE-2026-33871`, `CVE-2026-42587` | 4.1.132–133.Final |
| `io.netty:netty-handler` | `CVE-2026-44249`, `CVE-2026-45416`, `CVE-2026-50010` | 4.1.135.Final |
| `io.netty:netty-resolver-dns` | `CVE-2026-45674`, `CVE-2026-47691` | 4.1.135.Final |
| `org.apache.kafka:kafka-clients` | `CVE-2026-35554` | 3.9.2 |
| `org.apache.tomcat.embed:tomcat-embed-core` | `CVE-2026-41293`, `CVE-2026-43512`, `CVE-2026-43515`, `CVE-2026-24734`, `CVE-2026-24880`, `CVE-2026-34483`, `CVE-2026-41284`, `CVE-2026-42498`, `CVE-2026-43513` | 10.1.55 (Spring Boot BOM) |
| `org.bouncycastle:bcprov-jdk18on` | `CVE-2025-14813` | 1.80.2 |
| `org.lz4:lz4-java` | `CVE-2025-12183` | 1.8.1 |
| `org.postgresql:postgresql` | `CVE-2026-42198` | 42.7.11 |
| `org.springframework.ai:spring-ai-{client-chat,model}` | `CVE-2026-41712`, `CVE-2026-41713` | 1.0.7 |
| `org.springframework.boot:spring-boot` | `CVE-2026-40973` | 3.5.14 |
| `org.springframework.kafka:spring-kafka` | `CVE-2026-41731` | 3.3.16 |
| `org.springframework.security:spring-security-web` | `CVE-2026-22732` | 6.5.9 |

### Distroless base image (1 CVE)

**Remediation:** next base-image digest refresh.

| Package | Waived CVE | Fixed in |
|---|---|---|
| `liblcms2-2` (debian 12) | `CVE-2026-41254` | 2.14-2+deb12u1 |

The fix landed after the pinned distroless nonroot digest
(`sha256:7e37784d…`) was cut. Closes on the monthly base-image refresh.

## Trivy scan status (latest)

- **Target:** `uptimecrew/expense-api:0.1.0`
- **Date:** 2026-07-01
- **Command:** `trivy image --severity HIGH,CRITICAL --ignore-unfixed --ignorefile expense-api/.trivyignore uptimecrew/expense-api:0.1.0`
- **Result:** 0 non-waived HIGH/CRITICAL. Exit code 0. 32 unique CVEs
  waived (see table above), all with a 2026-08-01 review deadline.
