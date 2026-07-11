# expense-api GitOps (W6D2)

This document describes how `expense-api`'s cluster state is reconciled from
the sibling GitOps config repo by Argo CD, and how the app repo's CI opens
image-bump PRs against that config repo.

## Repos

| Role       | Repo                                                                       |
| ---------- | -------------------------------------------------------------------------- |
| App        | `AI-Native-2026-06-01-Intuit/uptimecrew-expense` (this repo)               |
| Config     | `AI-Native-2026-06-01-Intuit/pranav-kuchibhotla-expense-config`            |

The app repo owns source code, tests, the container image build, and the
image push to ECR. It **does not** own cluster state. Manifests under
`manifests/` here are still tracked as the source of truth for the W5D3
local cluster smoke workflow (`k8s-ci.yml`), but the authoritative version
for the Argo-reconciled envs lives in the config repo under `base/` and
`overlays/{dev,staging,prod}/`.

## Config repo layout

```
base/                          # environment-neutral manifests
  namespace, deployment, service, configmap, secret placeholder, hpa, ingress
overlays/dev/                  # namespace expense-dev, replicas=1, dev config
overlays/staging/              # namespace expense-staging, replicas=2, staging config
overlays/prod/                 # namespace expense-prod, replicas=3, prod config
argocd/projects/expense.yaml
argocd/applications/expense-api-dev.yaml     # standalone dev App (bootstrap)
argocd/applicationsets/expense-api-envs.yaml # matrix generator for dev/staging/prod
argocd-system/notifications-cm.yaml          # Slack notifications config
```

## Reconcile loop

1. Developer merges a change into `main` in the app repo.
2. `ci.yml` `build-test` runs. On green, `call-build-and-push` builds the
   image and pushes it to ECR tagged with `${{ github.sha }}` (and floating
   `:main`).
3. `bump-gitops-dev` calls the reusable `_bump-config.yml`, which:
   - Checks out the config repo using `secrets.GITOPS_REPO_TOKEN` (a
     fine-grained PAT scoped to that repo only — `contents: write` +
     `pull-requests: write`).
   - Runs `kustomize edit set image` in `overlays/dev` to pin the image
     tag to the just-pushed SHA.
   - Opens a PR against the config repo's `main` branch.
4. A human reviews and merges the PR in the config repo.
5. Argo CD polls (or webhook) the config repo, sees the change, and
   reconciles `overlays/dev` into namespace `expense-dev`.
6. Staging and prod are promoted by follow-up config-repo PRs (either
   hand-authored or by re-running `_bump-config.yml` with a different
   `overlay-path`).

**The app repo pipeline never talks to a Kubernetes API.** No `kubectl`,
no `kubeconfig`, no `EKS_KUBECONFIG` secret, no `aws eks update-kubeconfig`
step exists in `.github/workflows/`. The only cluster-adjacent workflow,
`k8s-ci.yml`, spins up an ephemeral k3d cluster inside the runner for smoke
tests and tears it down; it does not reach any shared or production cluster.

## Drift behavior

Argo CD's `Application` sync policy for `expense-api-dev` is:

```yaml
syncPolicy:
  automated:
    prune: true
    selfHeal: true
  syncOptions:
    - CreateNamespace=true
    - ServerSideApply=true
```

- **Automated sync** applies committed changes without human intervention.
- **Prune** deletes resources removed from the manifests on the next
  reconcile (so `git rm` in the config repo actually removes the object
  from the cluster).
- **SelfHeal** reverts direct edits made via `kubectl edit` / `kubectl
  scale` back to the committed spec. This is the guard against "hotfix
  drift" where someone patches prod out of band and forgets to update git.

The `ApplicationSet` (`expense-api-envs.yaml`) sets
`spec.syncPolicy.preserveResourcesOnDeletion: true` so that deleting the
ApplicationSet (or removing an env from its generator list) does NOT cascade
into deleting the workloads Argo was managing. That guardrail matters for
prod: an accidental generator edit shouldn't blow away the running app.

### Self-heal drift experiment (evidence pending)

To capture evidence of self-heal working, run against a freshly-synced
`expense-api-dev`:

```
kubectl -n expense-dev scale deploy/expense-api --replicas=3
# wait ~30s for the next reconcile
kubectl -n argocd logs deploy/argocd-application-controller \
  | grep -E 'expense-api-dev|Skipping self-heal|Syncing' | tail -40
kubectl -n expense-dev get deploy/expense-api -o jsonpath='{.spec.replicas}'
# expected: back to overlays/dev value (1)
```

<!-- self-heal-log-excerpt: CAPTURED 2026-07-11 on k3d-expense.
Procedure:
  kubectl -n expense-dev scale deploy/expense-api --replicas=3
  # wait ~30s
  kubectl -n expense-dev get deploy expense-api -o jsonpath='{.spec.replicas}'
Result (argocd-application-controller log excerpt):
  11:08:25Z Updated sync status: Synced -> OutOfSync application=expense-api-dev
  11:08:25Z Initialized new operation: {SyncOperation Prune:true ... Resources:[apps/Deployment/expense-api]}
  11:08:25Z Syncing application=argocd/expense-api-dev syncId=00001-nifsp
  11:08:25Z Adding resource result, status: 'Synced', message: 'deployment.apps/expense-api configured'
  11:08:25Z Partial sync operation ... succeeded reason=OperationCompleted
  11:08:25Z Updated sync status: OutOfSync -> Synced
Live confirm: kubectl -n expense-dev get deploy expense-api -o jsonpath='{.spec.replicas}' => 1
-->

## Project-scoped RBAC

The `AppProject` named `expense` in `argocd/projects/expense.yaml`:

- `sourceRepos`: **only** the config repo URL, verbatim — no wildcards.
- `destinations`: only the three env namespaces on
  `https://kubernetes.default.svc` (in-cluster). No cross-cluster.
- `clusterResourceWhitelist: []` — no cluster-scoped kinds allowed.
- `namespaceResourceWhitelist`: an explicit allow-list of the kinds we
  actually ship (Deployment, Service, ConfigMap, Secret, HPA, Ingress).
- `namespaceResourceBlacklist`: `ResourceQuota` and `LimitRange` are
  denied — those belong to the cluster admin's namespace bootstrap,
  not to the app's GitOps flow. Applying them from `expense` would let a
  team change their own quotas by PR.
- `roles`: `developers` (read-only on the project's Applications) and
  `releasers` (sync + override on dev/staging only; prod requires the
  admin role, and even then the weekend `syncWindow` denies auto-sync).
- `syncWindows`: a weekend deny window covering `overlays/prod` so
  automated sync cannot land a prod change on Saturday or Sunday.

The negative test is that a "rogue" `Application` in the same project
targeting `kube-system` should be rejected by the AppProject destination
whitelist. Argo returns:

```
Application destination server 'https://kubernetes.default.svc' and
namespace 'kube-system' do not match any of the allowed destinations
in project 'expense'
```

<!-- rogue-app-rejection-message: CAPTURED 2026-07-10 on k3d-expense.
Command:
  kubectl apply -f - <<'YAML'
  apiVersion: argoproj.io/v1alpha1
  kind: Application
  metadata: { name: rogue-kube-system, namespace: argocd }
  spec:
    project: expense
    source: { repoURL: ...expense-config.git, targetRevision: main, path: overlays/dev }
    destination: { server: https://kubernetes.default.svc, namespace: kube-system }
  YAML
Result (kubectl -n argocd get application rogue-kube-system -o jsonpath='{.status.conditions}'):
  [{"type":"InvalidSpecError","message":
    "application destination server 'https://kubernetes.default.svc' and
     namespace 'kube-system' do not match any of the allowed destinations
     in project 'expense'"}]
-->

## Local verification caveats (k3d + Argo CD v2.11.7)

Two orthogonal issues surfaced while verifying end-to-end on `k3d-expense`
(k3s v1.35.5) with Argo CD v2.11.7; both are documented so they aren't
mistaken for GitOps bugs:

1. **`.status.terminatingReplicas` schema mismatch.** k3s v1.35 emits a
   `Deployment.status.terminatingReplicas` field that Argo CD v2.11.7's
   embedded OpenAPI schema does not know, so structured-merge diff fails
   with `ComparisonError: field not declared in schema`. Argo sync itself
   still works (server-side apply reconciles fine), and selfHeal fires as
   soon as a fresh diff succeeds — but the app can flap between
   `Synced` and `Unknown` until Argo CD is upgraded to a build with the
   updated schema (>= v2.12). Upgrading Argo CD is the clean fix.

2. **Staging / prod dependency stack.** The initial staging/prod build
   crashlooped on `Unable to determine Dialect without JDBC metadata`
   because those overlays had no reachable Postgres/Redis/Mongo/Kafka —
   dev inherits them from the W5D3 `k8s-up.sh` apply flow, but that flow
   was never wired for the two other namespaces. Fixed by adding a
   namespace-neutral dependency stack under `deps/` in the config repo
   (Postgres+initdb ConfigMap, Redis, Mongo, Kafka) that staging and prod
   include via `resources: [../../deps]`. Dev deliberately does NOT
   include `deps/` — its dependencies are still managed out-of-band by
   the W5D3 flow, and duplicating them here would collide with the
   already-running kubectl-owned copies. After this fix, all three
   Applications report `Synced` + `Healthy`:

   ```
   NAME                  SYNC STATUS   HEALTH STATUS
   expense-api-dev       Synced        Healthy
   expense-api-prod      Synced        Healthy
   expense-api-staging   Synced        Healthy
   ```

3. **Live targetRevision is `w6d2-implementation` for local verification.**
   The committed YAML in the config repo (both `Application` and
   `ApplicationSet`) points at `main`, per the reconcile-loop design. For
   this pre-merge verification only, the live cluster resources were
   patched to `targetRevision: w6d2-implementation` so Argo could read the
   not-yet-merged manifests. The git-tracked value stays `main`; a
   post-merge re-sync will pick up `main` automatically.

## Out of scope for W6D2

The following are intentionally NOT migrated into GitOps in this cutover:

- **Dependencies (`postgres`, `redis`, `mongo`, `kafka`)**. These need a
  `postgres-initdb` ConfigMap built at apply time from `db/V1__schema.sql`
  and `expense-api/src/main/resources/db/migration/V3__event_outbox.sql`,
  which Argo cannot reproduce declaratively. The `k8s-up.sh` /
  `k8s-ci.yml` seeding pattern remains the source of truth for those.
- **Observability CRDs** (ServiceMonitor, PrometheusRule,
  AlertmanagerConfig). These require the Prometheus Operator CRDs to be
  installed in the target cluster before Argo can sync them. If the CRDs
  are absent (as they are on a bare k3d), Argo would fail health with
  `MissingKind`. Adding them will be a follow-up once
  `kube-prometheus-stack` is itself managed by Argo (or explicitly
  bootstrapped by cluster admin).
- **Cluster bootstrap** (Argo CD itself, ingress-nginx). Argo CD is
  installed once via a pinned manifest URL (`v2.11.7 install.yaml`), not
  via GitOps. Bootstrapping Argo with Argo is out of scope here.
- **Prod on EKS**. `overlays/prod` targets the local `k3d-expense` cluster
  via `https://kubernetes.default.svc` for W6D2. Real prod on EKS would
  require a separate Argo instance and a separate destination in the
  AppProject; that's a later week's work.

## argocd-author audit

<!-- argocd-author-audit: PENDING. The Claude Code environment used to
  author these manifests does not currently have the argocd-author skill
  loaded; audit was performed manually against the checklist below:
    - AppProject has no `*` in sourceRepos, destinations, or resource lists
    - Application syncPolicy has both prune and selfHeal enabled
    - ApplicationSet uses preserveResourcesOnDeletion: true
    - No Application in the repo uses `project: default`
    - Notifications ConfigMap subscribes only on failure / degraded, not success
  Re-audit with the skill once available; attach the audit output here. -->

## `preserveResourcesOnDeletion` experiment

The intent: deleting the `ApplicationSet` should not delete the underlying
`Deployment`/`Service` in each namespace, so that a mis-authored generator
change is recoverable by re-applying the ApplicationSet without an outage.

Procedure:

```
# 1. Confirm the ApplicationSet is managing the three envs.
argocd appset get expense-api-envs
# 2. Snapshot the current pods.
kubectl get pods -n expense-dev -o name > /tmp/pods.before
# 3. Delete just the ApplicationSet (NOT the child Applications).
kubectl -n argocd delete applicationset expense-api-envs --wait=true
# 4. Confirm Applications and workloads still exist.
argocd app list --project expense
kubectl get pods -n expense-dev -o name > /tmp/pods.after
diff /tmp/pods.before /tmp/pods.after   # expected: no diff
# 5. Re-apply the ApplicationSet to restore ownership.
kubectl apply -f argocd/applicationsets/expense-api-envs.yaml -n argocd
```

<!-- preserve-resources-experiment: CAPTURED 2026-07-11 on k3d-expense.
Procedure:
  kubectl -n argocd get applications -o name | sort > /tmp/apps.before
  kubectl -n expense-{dev,staging,prod} get deploy expense-api -o name > /tmp/deps.<env>.before
  kubectl -n argocd delete applicationset expense-api-envs --wait=true
  # (Argo garbage-collected the 3 child Applications, expected — the guarantee
  # is on managed workloads, not on the child Application objects.)
  kubectl -n expense-{dev,staging,prod} get deploy expense-api -o name
Result:
  applicationset.argoproj.io "expense-api-envs" deleted
  APPS diff: expense-api-{dev,staging,prod} removed (Applications were deleted)
  DEV/STG/PROD deploy diff: EMPTY — deployment.apps/expense-api still present
    in all three namespaces after AppSet delete. preserveResourcesOnDeletion
    prevented cascade delete of the actual workloads.
Restore: kubectl apply -f argocd/applicationsets/expense-api-envs.yaml
  (child Applications regenerated; sync status returns to Synced.)
-->

## Slack notification wiring

Notifications go through a Slack Incoming Webhook. The URL lives at key
`slack-webhook-url` in `argocd-notifications-secret` (namespace `argocd`),
never in git. The ConfigMap declares:

- `service.webhook.slack-incoming` — the outbound service
- `trigger.on-sync-failed` and `trigger.on-health-degraded` (nil-guarded)
- `template.app-sync-failed` and `template.app-health-degraded` — plain
  `{"text": "..."}` payloads (Slack Incoming Webhook shape)
- One subscription: `webhook:slack-incoming` for apps labeled `team=expense`

**Round-trip evidence.** A direct POST from inside the k3d-expense
cluster to the Slack webhook returned HTTP 200 (verified 2026-07-11):

```
$ kubectl -n argocd run curl-test --image=curlimages/curl:8.9.1 --restart=Never \
    --rm -i -- curl -sS -o /dev/null -w '%{http_code}\n' \
    -X POST -H 'Content-Type: application/json' \
    --data '{"text":":white_check_mark: W6D2 notification-plumbing test..."}' \
    "<SECRET_WEBHOOK_URL>"
200
```

The message appeared in the target Slack channel — screenshot captured
separately (webhook URL not shown in the screenshot).

**Argo-controller path is present but not yet firing.** The
notifications-controller in the v2.11.7 install responds "notification
service 'webhook' is not supported" for the CM-declared
`service.webhook.slack-incoming`. The engine's webhook service ships in
`notifications-engine v0.4.1` (which v2.11.7 depends on), but the
argocd-notifications-controller wiring in v2.11.7 does not register the
webhook service by default. Options tracked:

1. Upgrade to Argo CD v2.12+ (webhook is registered by default there).
2. Switch to the built-in `slack` service with a proper Slack bot token
   (xoxb-...) once a Slack App is provisioned.
3. Deploy a tiny in-cluster "webhook shim" that Argo's `slack` service
   posts to and which forwards to the Incoming Webhook.

Option 1 is preferred and is a v6d3 follow-up. The wiring in the config
repo is already in the correct shape for Option 1 — no ConfigMap changes
needed when Argo is upgraded.

## Secrets outside git

The GitOps repo checks in a placeholder `Secret` (`expense-api-secrets`)
with a sentinel value that will fail auth. The real database password is
seeded by the same out-of-band mechanism as the W5D3 cluster (`k8s-up.sh`
or the k8s-ci workflow):

```
kubectl create secret generic expense-api-secrets -n expense-<env> \
  --from-literal=SPRING_DATASOURCE_PASSWORD="$CI_PG_PASSWORD" \
  --dry-run=client -o yaml | kubectl apply -f -
```

Argo is told to ignore that Secret's `data` field via a per-resource
`ignoreDifferences` in the Application (see `overlays/*/kustomization.yaml`
patches) so self-heal does not overwrite the seeded value back to the
placeholder. A future iteration should replace this with External Secrets
Operator or SOPS-encrypted secrets in the config repo.
