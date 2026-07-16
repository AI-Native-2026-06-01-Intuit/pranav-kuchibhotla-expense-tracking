# expense-api SRE capstone (W6D5)

W6D5 closes out the Week 6 SRE arc. Substrate landed W6D1–D4; this file
documents (a) what shipped this week, (b) the SLO / cost contract the
service is measured against, (c) which parts are live and which are
static/local because of platform limitations in this cohort, and (d) how
this hands off to Week 7.

## Platform access / omissions

The W6D5 brief says a shared EKS cluster is provided. **It is not.** The
cohort lead (Kinza) confirmed no EKS access. Therefore the following
things are **not claimed** anywhere in W6D5 work:

- No live KEDA scale-from-zero on the SQS queue.
- No live Karpenter spot / on-demand node provision.
- No AWS X-Ray console screenshots.
- No same-trace Tempo ↔ X-Ray pivot.
- No Argo CD sync of the new `k8s/expense-api/` and `k8s/karpenter/`
  manifests.
- No `./gradlew` deploy against a real cluster.

What is claimed: static templates + local validation. See
[`docs/evidence/w6d5-platform-gaps.md`](docs/evidence/w6d5-platform-gaps.md)
for the exact `kubectl` / `argocd` / `k6` prep-check output, and
[`docs/evidence/w6d5-static-validation.md`](docs/evidence/w6d5-static-validation.md)
for what was validated locally.

## W6D1–D4 substrate (recap)

- **W6D1:** container hardening. Distroless runtime image, non-root UID,
  Trivy `HIGH,CRITICAL` gate, healthcheck binary rebuilt on Go stdlib
  CVEs, `.trivyignore` honored by the pipeline.
- **W6D2:** GitOps. Argo CD `AppProject` (strict, prod syncWindow) plus
  `ApplicationSet` for dev/staging/prod; Slack notifications on
  `sync-failed` + `health-degraded`.
- **W6D3:** infra as code. CloudFormation substrates
  (`expense-network-dev`, `expense-artifacts-dev`, `expense-app-dev`),
  Secrets Manager–managed DB password.
- **W6D4:** LLM cost accountability. `CostMiddleware` computes per-request
  USD from `PriceBook`, emits EMF, tallies daily spend in Redis, and
  writes `X-Cost-Usd` on the response. `expense-cost-dev` stack owns the
  CloudWatch alarm. See [`COST.md`](COST.md).

## W6D5 artifacts

| Artifact | Repo | Path | Status |
| --- | --- | --- | --- |
| X-Ray sampling rule (CFN) | config | `cfn/expense-observability-dev.yaml` | static; `cfn-lint` + `validate-template` pass |
| ADOT collector (OTLP → Tempo + X-Ray) | config | `k8s/expense-api/adot-collector.yaml` | static; parse-only |
| KEDA ScaledObject (SQS) | config | `k8s/expense-api/expense-worker-scaledobject.yaml` | static; parse-only |
| Custom-metric HPA | config | `k8s/expense-api/hpa.yaml` | static; parse-only |
| PDB (maxUnavailable 25%) | config | `k8s/expense-api/pdb.yaml` | static; parse-only |
| Karpenter NodePool (spot+on-demand) | config | `k8s/karpenter/expense-mixed.yaml` | static; parse-only |
| k6 SLO gate | app | `expense-api/loadtests/expense-api-p99.js` | static thresholds; live run gated on `run_live_load=true` |
| Load workflow | app | `.github/workflows/load.yml` | static job on PR; live job manual only |
| SQS enqueue spike | app | `expense-api/scripts/w6d5-integration-spike.sh` | DRY_RUN=1 default; dry-run verified locally |

## SLOs

| SLI | Objective | Where enforced |
| --- | --- | --- |
| p99 latency (ms) | `< 600` | `http_req_duration: ['p(99)<600']` |
| Error rate | `< 0.01` | `http_req_failed: ['rate<0.01']` |
| Cost per request (USD) | `p95 < 0.004` | `cost_per_request_usd: ['p(95)<0.004']` |

The cost budget re-uses the `X-Cost-Usd` header the W6D4 middleware
already writes on responses (see `expense-api/COST.md`), so no new
runtime plumbing is required for the gate.

### How k6 maps to SLOs

The k6 script encodes each SLO row above as a `thresholds` entry.
`k6` fails the run with a non-zero exit code if any threshold is
breached, which the CI live job propagates into a red check. There is
no per-scenario override that would let one workload eat another's
budget: `http_req_duration` and `http_req_failed` are global, and the
cost `Trend` is added once per response so its p95 is a fleet number.

## HPA design rationale

Custom-metric-only (`expense_inflight_requests` averaged over pods),
not CPU utilization. The service is I/O-bound on outbound LLM calls;
CPU utilization stays low even when a pod is at its inflight-request
ceiling, so a CPU-based HPA under-scales exactly when latency starts
climbing. Micrometer already exposes this gauge on
`/actuator/prometheus`; prometheus-adapter is the missing platform
piece (documented as an omission).

Scale-down `stabilizationWindowSeconds: 600` on purpose — every
scale-down destroys warm JVM state and LLM prompt-cache locality, so
we accept over-provisioning for a 10-minute window rather than
thrashing during small dips.

## KEDA operator identity

`identityOwner: operator` in both the `TriggerAuthentication` and the
per-trigger metadata. Consequence: the KEDA operator pod (in namespace
`keda`) holds the IRSA role for `sqs:GetQueueAttributes` /
`sqs:ReceiveMessage`; workload pods never receive SQS credentials. This
matches the least-privilege story for the substrate.

## X-Ray sampling rationale

`ReservoirSize: 10` guarantees 10 traces/sec of evidence even during
quiet periods, so we never have zero data to debug from. `FixedRate:
0.05` is the 5% probabilistic sample above the reservoir. **Never
`FixedRate: 0`**, which would disable telemetry outside the reservoir
window and defeat the point of the stack. The sampling decision lives
in AWS, not the app, which is why the app code does not import the
X-Ray SDK — the ADOT collector's `awsxray` exporter honors whatever the
X-Ray API returns.

## Karpenter + PDB rationale

The NodePool is `spot` first (cheapest), `on-demand` as guaranteed
fallback. `limits.cpu: 200` caps runaway spend even if both HPA and
KEDA hit their max concurrently. `consolidateAfter: 600s` matches the
HPA scale-down stabilization so we don't consolidate a node the HPA
was about to fill back up.

The PDB uses `maxUnavailable: 25%` so voluntary disruptions
(consolidation, drains, upgrades) can proceed in parallel batches at
larger replica counts, but at the 2-replica floor at least one pod
stays serving traffic during a drain. `minAvailable: 2` was considered
but does not scale with the HPA — during a large scale-up event, only
guaranteeing 2 available pods is insufficient headroom.

## Local validation summary

App repo:

- `./gradlew :expense-api:test` — **PASS** (cached / up-to-date).
- `bash -n expense-api/scripts/w6d5-integration-spike.sh` — **PASS**.
- `DRY_RUN=1 COUNT=3 …/w6d5-integration-spike.sh` — **PASS**, printed
  three sample messages, no AWS call.
- `node --check expense-api/loadtests/expense-api-p99.js` — **PASS**.
- Contract greps for the three SLO thresholds, `tenant-synth`,
  workload weights, and `assertMixWeightsSumToOne` — **PASS**.
- Secret grep (`sk-`, `LLM_API_KEY=`) confirms no real key material in
  the new files — **PASS**.
- `k6` binary itself is not installed on the local box; live k6 run
  therefore not executed.

Config repo (see its own `docs/evidence/w6d5-static-validation.md`):

- `cfn-lint` PASS.
- `aws cloudformation validate-template` PASS.
- YAML parse PASS across 5 manifests.
- Contract greps PASS.

## Runtime follow-up when EKS exists

1. Platform installs KEDA + Karpenter + ADOT operators and provisions
   the `EC2NodeClass` "default" plus the IRSA roles referenced in the
   manifests.
2. Deploy the CFN stack `expense-observability-dev.yaml`.
3. Apply `k8s/expense-api/*` and `k8s/karpenter/*` through Argo CD
   (add them to the ApplicationSet).
4. Fire the workflow: `gh workflow run load.yml -f target_url=<url>
   -f run_live_load=true`.
5. Enqueue with `DRY_RUN=0 QUEUE_URL=<url>
   expense-api/scripts/w6d5-integration-spike.sh` to demonstrate
   KEDA scale-from-zero.

## Loadtest-author audit

An earlier draft of the k6 script was reviewed. Findings:

**Accepted (kept in the final):**

- Exact SLO threshold mapping: `p(99)<600`, `rate<0.01`, `p(95)<0.004`
  copied verbatim into `options.thresholds`.
- The cost threshold as a first-class SLO alongside latency and error
  rate — not demoted to an informational metric.
- `X-Cost-Usd` header read is the primary cost signal, reusing the
  W6D4 middleware contract instead of asking the load driver to
  estimate USD from token counts.

**Rejected (would have shipped without this review):**

- **Invented SLO numbers.** An earlier suggestion softened p99 to
  `<800ms` because "600 might be tight without a real cluster." That
  changes the contract to hide risk instead of measure it. Kept 600.
- **Silently renormalized workload mix.** An earlier version had
  weights `0.6 / 0.3 / 0.2` (sum 1.1) and quietly divided by the sum
  at pick time. Replaced with `assertMixWeightsSumToOne` that throws
  on drift, so a review that changes one weight and forgets the
  others gets a loud failure instead of quiet normalization. The CI
  static job also greps for the assertion function name to prevent
  it being deleted.
- **Dropped `cost_per_request_usd` threshold.** An earlier version
  moved the cost `Trend` out of `thresholds` and only surfaced it in
  the summary. That would have let a runaway prompt price the fleet
  into a $0.02/request regime with a green build. Cost stays in
  thresholds.

## W7 readiness checks

Going into Week 7 the service needs three things to be true, each of
which is now testable via a file, not a screenshot:

- **SLO budget defined and enforceable.** k6 gate lives in
  `expense-api/loadtests/expense-api-p99.js`; CI static job blocks
  loosening it.
- **Cost budget defined and enforceable.** `X-Cost-Usd` written by
  `CostMiddleware` (W6D4); `p(95)<0.004` gate written here; CloudWatch
  alarm defined in `expense-cost-dev` (W6D4).
- **AI-tool audit.** Loadtest-author review above is checked in; a
  future review can diff against it.
