# syntax=docker/dockerfile:1.7

# --- Stage 1: builder ---------------------------------------------------------
FROM eclipse-temurin:21-jdk-jammy@sha256:801b7e1a9c4befaf82bf9a2a58025ef43a7694bbc84779187ad0524d84742772 AS builder
WORKDIR /workspace

# Copy Gradle wrapper + build scripts first so dependency resolution caches.
COPY gradlew gradlew.bat ./
COPY gradle ./gradle
COPY build.gradle ./

RUN chmod +x ./gradlew

# Warm the Gradle dependency cache. The BuildKit cache mount survives across
# builds so wrapper + deps are not re-downloaded on every rebuild.
RUN --mount=type=cache,target=/root/.gradle,sharing=locked \
    ./gradlew --no-daemon dependencies

# Copy sources after dependency warm-up so source-only edits skip the above layer.
COPY src ./src

RUN --mount=type=cache,target=/root/.gradle,sharing=locked \
    ./gradlew --no-daemon bootJar -x test

# --- Stage 2: extractor -------------------------------------------------------
FROM eclipse-temurin:21-jre-jammy@sha256:199aebeb3adcde4910695cdebfe782ada38dadb6cc8013159b58d3724451befd AS extractor
WORKDIR /extract
COPY --from=builder /workspace/build/libs/*.jar app.jar
RUN java -Djarmode=layertools -jar app.jar extract --destination .

# --- Stage 3: runtime ---------------------------------------------------------
FROM gcr.io/distroless/java21-debian12:nonroot@sha256:7e37784d94dccbf5ccb195c73b295f5ad00cd266512dfbac12eb9c3c28f8077d AS runtime

ARG APP_VERSION=0.0.0
ARG GIT_SHA=unset
ARG TARGETARCH

LABEL org.opencontainers.image.title="expense-api" \
      org.opencontainers.image.version="${APP_VERSION}" \
      org.opencontainers.image.revision="${GIT_SHA}" \
      org.opencontainers.image.source="https://github.com/Pranav-Kuchibhotla/uptimecrew-expense" \
      org.opencontainers.image.licenses="Apache-2.0"

USER 65532
WORKDIR /home/nonroot

COPY --from=extractor /extract/dependencies/          ./
COPY --from=extractor /extract/spring-boot-loader/    ./
COPY --from=extractor /extract/snapshot-dependencies/ ./
COPY --from=extractor /extract/application/           ./

COPY docker/healthcheck-${TARGETARCH} /home/nonroot/healthcheck

EXPOSE 8080

HEALTHCHECK --interval=30s --timeout=3s --start-period=30s --retries=3 \
  CMD ["/home/nonroot/healthcheck"]

ENTRYPOINT ["java","org.springframework.boot.loader.launch.JarLauncher"]
