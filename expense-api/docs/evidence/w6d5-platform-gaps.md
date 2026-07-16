# W6D5 platform gaps (app repo view)

Mirrors `docs/evidence/w6d5-platform-gaps.md` in the config repo. See
that file for the canonical prep-check output. This file summarizes the
gaps as they affect the **app repo** artifacts and records how the app
branch is layered.

## Branch layering

`w6d5-implementation` in this repo is stacked on `w6d4-implementation`,
not on `main`. Reason: the W6D4 app changes
(`expense-api/COST.md`, `expense-api/src/main/java/com/uptimecrew/expense/llmproxy/cost/*`,
etc.) have not been merged to `main` yet. `main` still points at
`122cfd9 Merge pull request #12 from AI-Native-2026-06-01-Intuit/w6d2-implementation`.

To rebase onto main once the W6D4 app PR merges:

```sh
git fetch github
git rebase github/main
```

## Cohort clarification

The W6D5 brief said a shared EKS cluster would be provided. Kinza
clarified no EKS cluster is available. All k8s/karpenter/observability
work is therefore static/local content.

## Gaps that affect the app repo specifically

- **k6 is not installed** on the local dev box
  (`zsh: command not found: k6`). The k6 script is syntax-validated via
  `node --check`, but no live k6 run was executed here. Live runs go
  through `.github/workflows/load.yml`'s `live` job, which is gated on
  `workflow_dispatch` + `run_live_load=true` + a non-empty `target_url`
  so the workflow does not fail every PR just because no cluster
  exists.
- **`expense_inflight_requests` custom metric** is exposed by the app
  via Micrometer on `/actuator/prometheus`, but the HPA target on that
  metric requires `prometheus-adapter` to be installed and configured
  to publish into `custom.metrics.k8s.io`. That is a platform
  dependency, not present in any cluster we can reach.
- **KEDA operator IRSA role** and the SQS queue
  `expense-ingest-dev` are platform-owned. The spike script
  (`expense-api/scripts/w6d5-integration-spike.sh`) is DRY_RUN=1 by
  default; DRY_RUN=0 requires `QUEUE_URL` to be exported and will only
  send if `aws` CLI can authenticate.

## What this PR does NOT claim

- No live k6 run against a cluster URL.
- No demonstration of KEDA scale-from-zero.
- No `X-Cost-Usd` header measured under a live k6 workload (the header
  itself is verified by W6D4 unit + integration tests; only the k6
  wiring is new here).
- No X-Ray console screenshots or Tempo ↔ X-Ray same-trace pivots.

## What this PR does claim

- The k6 script contains the exact SLO thresholds and workload mix
  metadata; the CI static job asserts this on every PR.
- The SQS enqueue spike runs cleanly in DRY_RUN mode without touching
  AWS.
- `./gradlew :expense-api:test` passes (unchanged; no app code changed).
- No secrets are present in the loadtest, workflow, or spike script.
