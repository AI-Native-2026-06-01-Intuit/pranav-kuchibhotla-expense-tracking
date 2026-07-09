# Local dev loop with live reload

The base compose stack runs the published image `uptimecrew/expense-api:0.1.0`, so
code changes require a rebuild. For a tight edit loop, use the `dev` profile: it
adds an `expense-api-dev` service that bind-mounts `./expense-api` into a JDK
container and re-runs the jar Gradle produces on every rebuild.

## One-time setup

```bash
cp envs/expense.env.example envs/expense.env       # if not already done
printf 'expense-dev-password' > secrets/pg_password.txt
```

## The two-terminal loop

**Terminal 1 — continuous Gradle rebuild** (writes `expense-api/build/libs/expense-api-*.jar`):

```bash
./gradlew :expense-api:bootJar --continuous
```

Gradle stays running and re-emits the jar every time a source file changes.

**Terminal 2 — bring up the dev service** (Postgres/Redis/Kafka come along via `depends_on`):

```bash
docker compose --profile dev up -d expense-api-dev
docker compose --profile dev logs -f expense-api-dev
```

The dev container starts the newest jar under `expense-api/build/libs/` with
Spring Boot devtools enabled, so the JVM restarts within seconds of Gradle
writing a new jar. Nothing needs to be restarted on the compose side.

Stop the dev service without touching Postgres/Redis/Kafka:

```bash
docker compose --profile dev stop expense-api-dev
docker compose --profile dev rm -f expense-api-dev
```

## Endpoints & ports

| Purpose                   | Port  | Notes                                            |
|---------------------------|-------|--------------------------------------------------|
| Published image HTTP      | 8080  | `expense-api` service (base compose)             |
| Smoke stack HTTP          | 18080 | `make smoke` runs an isolated project on this port so it can coexist with `make up` |
| Dev service HTTP          | 8081  | `expense-api-dev` service (dev profile)          |
| JDWP debugger (base)      | 5005  | Attach to `localhost:5005` from your IDE         |
| JDWP debugger (dev)       | 5006  | Attach to `localhost:5006` from your IDE         |

In IntelliJ / VS Code, create a remote JVM debug configuration pointing at
`localhost:5005` (published image) or `localhost:5006` (dev service). Debugger
does **not** suspend on start (`suspend=n`), so attaching is optional.

## Expected restart behavior

- Editing a Java source file triggers Gradle to rebuild the jar (Terminal 1).
- Devtools inside the running container notices the jar timestamp change and
  restarts the Spring context within ~1–2 seconds.
- HTTP requests briefly 503 during the restart and then succeed with the new code.
- Postgres/Redis/Kafka keep running — no data loss between reloads.
