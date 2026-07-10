# expense-api CI/CD pipeline (W6D1)

This document describes the GitHub Actions pipeline that builds, scans, publishes,
and deploys the `expense-api` service, together with the AWS OIDC federation that
makes AWS access possible without long-lived credentials.

## Repository facts

- Canonical GitHub slug: `AI-Native-2026-06-01-Intuit/pranav-kuchibhotla-expense-tracking`
- Remote also reachable via redirect: `AI-Native-2026-06-01-Intuit/uptimecrew-expense`
- Default branch on GitHub is currently `implementation`. W6D1 targets `main`
  because `main` is the branch the deploy pipeline is scoped to. See the waiver
  section below.

## Workflows

### `.github/workflows/ci.yml`

- Triggers on `pull_request` to `main` and on `push` to `main`, both restricted
  to paths under `expense-api/**` and the CI-owning workflow/action files.
- `build-test` job runs on every PR and every push to `main` using the
  `setup-build` composite action (Temurin 21 + Gradle cache), then
  `./gradlew build`. Test reports upload as an artifact.
- `call-build-and-push` job runs **only** on push to `main` (guarded by
  `if: github.event_name == 'push' && github.ref == 'refs/heads/main'`) and
  invokes the reusable `_build-and-push.yml` workflow. Pull requests never
  push images.

**Unit vs integration tests.** `./gradlew build` runs unit tests only
(`*Test.java`); `*IT.java` classes are excluded from the `test` task and run
under a separate `integrationTest` task. Integration tests require a running
Docker daemon plus Testcontainers-managed Postgres, Kafka, Mongo, and Redis,
and are not part of the CI gate — they run locally when a developer has
Docker configured, or in a dedicated integration environment. Branch
coverage verification (`jacocoTestCoverageVerification`) is measured over
the unit-test run only, so the gate reflects what unit tests actually cover
rather than what the wiring exercises transitively.

### `.github/workflows/_build-and-push.yml`

Reusable workflow triggered via `workflow_call`. Typed inputs: `image-tag`,
`also-tag-main`, `aws-region`, `ecr-repository`, `build-role-arn`. Steps:

1. `setup-build` composite for checkout + JDK + Gradle cache.
2. `./gradlew bootJar -x test` to produce the runnable jar.
3. `docker/build-push-action` builds the image locally (`load: true`).
4. Trivy scan with `severity: HIGH,CRITICAL` and `exit-code: 1` — HIGH or
   CRITICAL findings fail the workflow. Waivers are loaded from
   `expense-api/.trivyignore`, which tracks each waived CVE ID together
   with its remediation plan and next-review date in
   `expense-api/docker/SECURITY.md`. The gate still fires on any new CVE
   that isn't already in the waiver list.
5. `aws-actions/configure-aws-credentials` assumes the build role via OIDC.
6. `aws-actions/amazon-ecr-login` obtains an ECR docker login.
7. Push image tagged with the git SHA. Optionally also push `:main`.

**Note on ECR tag mutability:** the `uptimecrew/expense-api` ECR repository is
configured with `imageTagMutability: IMMUTABLE_WITH_EXCLUSION` and a single
wildcard exclusion filter `{filterType: WILDCARD, filter: "main"}`. This means:

- SHA-tagged images (e.g. `:abc1234…`) are **immutable** — they cannot be
  overwritten once pushed, which is what production deploys reference.
- The floating `:main` tag is **mutable** — it can be re-pushed on every
  green build of `main` so it always points at the latest tip.

The repo state can be reproduced with:

```sh
aws ecr put-image-tag-mutability \
  --repository-name uptimecrew/expense-api \
  --region us-east-1 \
  --image-tag-mutability IMMUTABLE_WITH_EXCLUSION \
  --image-tag-mutability-exclusion-filters filterType=WILDCARD,filter=main
```

The GitHub Actions build role is **not** granted `ecr:BatchDeleteImage` or
any other delete permission. CI never deletes or recreates the `main` tag —
it relies on the exclusion filter to permit re-tagging in place.

### `.github/workflows/deploy-prod.yml`

- `workflow_dispatch` only — no automatic prod deploy.
- Input `image-sha` must be exactly 40 lowercase hex characters. `validate-input`
  job asserts this before any AWS role is assumed.
- `deploy` job uses `environment: prod` (which pins the OIDC subject claim to
  `environment:prod`), assumes the prod role via OIDC, then runs
  `aws ecr describe-images` to confirm the referenced tag exists in ECR. If
  the image is missing the workflow fails before any deploy step runs.
- Concurrency group `expense-api-deploy-prod` with `cancel-in-progress: false`,
  so overlapping prod deploys queue rather than cancel each other.

### `.github/actions/setup-build/action.yml`

Composite action that runs `actions/setup-java` with Temurin 21 and
`gradle/actions/setup-gradle` for Gradle build caching. Cache is
`read-only` on branches other than `main` so PRs cannot poison the cache.
Callers are responsible for running `actions/checkout` before invoking
this composite — a local action reference (`./.github/actions/setup-build`)
is only resolvable once the runner has checked the repo out.

## OIDC roles

Two IAM roles federate GitHub Actions to AWS. There are no long-lived AWS
access-key or secret-key credentials in the repository or in Actions
secrets — every AWS call is authorized by a short-lived STS session
obtained via `aws-actions/configure-aws-credentials` with OIDC.

| Role                      | ARN                                                                 | Trust `sub` claim(s)                                                                                                                                                    | Permissions                       |
| ------------------------- | ------------------------------------------------------------------- | ----------------------------------------------------------------------------------------------------------------------------------------------------------------------- | --------------------------------- |
| `expense-api-build-push`  | `arn:aws:iam::726695008378:role/expense-api-build-push`             | `repo:AI-Native-2026-06-01-Intuit/pranav-kuchibhotla-expense-tracking:ref:refs/heads/main`, `repo:AI-Native-2026-06-01-Intuit/pranav-kuchibhotla-expense-tracking:environment:dev` | ECR push to `uptimecrew/expense-api` |
| `expense-api-prod-deploy` | `arn:aws:iam::726695008378:role/expense-api-prod-deploy`            | `repo:AI-Native-2026-06-01-Intuit/pranav-kuchibhotla-expense-tracking:environment:prod`                                                                                 | ECR read on `uptimecrew/expense-api` |

**PRs cannot assume either role.** The build role trust intentionally omits
`pull_request` and `pull_request_target`. The prod role trust is scoped to the
`prod` environment only, and no pull-request workflow uses `environment: prod`.

Trust policies live in the repo under
`expense-api/infra/oidc/trust-policy-build.json` and
`expense-api/infra/oidc/trust-policy-prod.json` so they are auditable and
can be reapplied to the role idempotently.

The OIDC provider is `arn:aws:iam::726695008378:oidc-provider/token.actions.githubusercontent.com`.

## Environments

- `dev` — targeted by future dev-deploy workflows; the build role trusts the
  `environment:dev` subject claim.
- `prod` — required for `deploy-prod.yml`. The prod role trusts only the
  `environment:prod` subject claim.

Both environments should exist in the GitHub UI (Settings → Environments).
Neither has required-reviewer protection. See waiver below.

## SHA pinning

Every third-party GitHub Action referenced by the W6D1 workflows and the
`setup-build` composite action is pinned to a full 40-character commit SHA
with a `# v<x.y.z>` comment. This is enforced by:

```sh
grep -RIn '@v[0-9]\+$' \
  .github/workflows/ci.yml \
  .github/workflows/_build-and-push.yml \
  .github/workflows/deploy-prod.yml \
  .github/actions/setup-build/action.yml
```

which must return no matches.

**Why:** a tag reference like `@v4` can be moved silently by the action's
maintainers, or replaced entirely if a maintainer key is compromised. A SHA
pin is content-addressed and cannot be moved. Dependabot (see
`.github/dependabot.yml`) proposes grouped weekly SHA bumps so we still
receive updates without giving up the pin.

Pre-existing workflows from prior weeks (`k8s-ci.yml`, `observability.yml`,
`compose-ci.yml`, `docker.yml`, `serverless.yml`, `web-ci.yml`) still use
`@vN` tag references. Those workflows predate W6D1 and are intentionally not
retrofitted in this PR to keep the change surface focused. The SHA-pinning
gate is scoped to the four W6D1-owned files listed above.

## Waivers

- **Required reviewer / advanced GitHub Environment protection.** The cohort
  announced that enterprise GitHub advanced protections (required reviewers,
  branch protection reviewer rules, environment protection rules gated by
  reviewers) are not available in this org. As a result, no reviewer-gated
  environment screenshot is submitted and the `prod` environment is created
  without required reviewers. `deploy-prod.yml` retains `environment: prod`
  and `concurrency.cancel-in-progress: false` per spec.
- **Default branch on GitHub.** The GitHub default branch is `implementation`,
  not `main`. An attempt to change it via `gh repo edit --default-branch main`
  failed with HTTP 404, which indicates that the current token lacks the
  admin rights necessary to mutate repository settings. All W6D1 workflow
  triggers, trust policy `sub` claims, and PR base branch remain `main`
  because `main` is the branch we treat as the release trunk regardless of
  the GitHub UI setting.
- **GitHub Environment provisioning.** Creating `dev` and `prod` environments
  via `gh api` returned HTTP 403 (`Must have admin rights to Repository`).
  The environments must be created in the GitHub UI by a repo admin (Settings
  → Environments → New environment) before `deploy-prod.yml` can run. This
  does not affect CI or the reusable build-and-push workflow.

## PR behavior

For a pull request targeting `main`:

- `ci.yml` `build-test` job runs, executing `./gradlew build`.
- No AWS role is assumed. No image is built by the reusable workflow.
- Trivy is not run on PRs (image build happens only in the reusable workflow,
  which is gated to push-on-main).

## `main` behavior

For a push to `main`:

- `ci.yml` `build-test` job runs.
- On success, `call-build-and-push` invokes `_build-and-push.yml`, which
  builds the image, runs the Trivy HIGH/CRITICAL gate, assumes the build
  role via OIDC, and pushes the image to ECR tagged with the git SHA (and
  optionally `:main`, subject to ECR tag mutability).

## Prod deploy behavior

Manually triggered via `workflow_dispatch` in the Actions UI:

1. Provide the 40-hex `image-sha` of a previously pushed image.
2. `validate-input` asserts the format.
3. `deploy` runs under `environment: prod`, assumes the prod role via OIDC,
   and confirms the tagged image exists in ECR before deploying.

The concurrency group `expense-api-deploy-prod` with
`cancel-in-progress: false` ensures overlapping deploys queue instead of
cancelling in flight.
