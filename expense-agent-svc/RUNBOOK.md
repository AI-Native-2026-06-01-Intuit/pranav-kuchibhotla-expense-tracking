# expense-agent-svc — On-call runbook

Operational runbook for the W7D5 multi-agent orchestration service.

## Vitals

| Field | Value |
|---|---|
| Service name | `expense-agent-svc` |
| Owning project | `expense` (Argo AppProject) |
| Application repository | `expense-agent-svc/` in this repo |
| Production namespace | `expense-svc` |
| Health endpoint | `GET /healthz` |
| Readiness endpoint | `GET /readyz` |
| Stream endpoint | `POST /v1/chat/stream` |
| Recursion limit | 25 (runtime `configurable.recursion_limit`) |
| Request budget | 25 000 `cost_usd_e5` |
| Retrieval deadline | 3 seconds |
| API deadline | 5 seconds |
| Synthesis deadline | 8 seconds |
| Monthly BudgetAction cap | USD 4 000 (100 % ACTUAL → APPLY_IAM_POLICY) |
| ECR image URI | `726695008378.dkr.ecr.us-east-1.amazonaws.com/expense-agent-svc` |
| Region | `us-east-1` |
| Config repo | `AI-Native-2026-06-01-Intuit/pranav-kuchibhotla-expense-config` |
| Proposed config path | `expense-agent-svc/overlays/prod` |
| Argo Application | `expense-agent-svc` (namespace `argocd`) |

Every graph invocation goes through `expense_agent_svc.graph.invocation_config(thread_id)` — a grep-enforced central helper (see `tests/test_recursion_limit.py`). If a new call site is added, the `recursion_limit` and `thread_id` follow automatically.

---

## Top five on-call signals

### Signal 1 — Synthesis cost p99 breach

**Symptom.** Per-request `cost_usd_e5` reported at the `synthesis_agent` boundary trends p99 above the request budget (25 000), or LangSmith runs show a step-function increase in synthesis input/output tokens.

**Likely causes.** Model regression at the provider, prompt bloat (docs/tool_results grew past the bounds in `_bounded_docs_for_prompt` / `_bounded_tool_results_for_prompt`), retry storm from Instructor `max_retries=2` combined with structured-output rejections, sampling misconfiguration causing spend attribution drift.

**Dashboard/query.** LangSmith project `expense-agent-svc-prod`; filter `run_type=chain` and `name=synthesis_agent`, group by `tenant_id` and by `X-Agent`. Authoritative cost is llm-proxy / CloudWatch on the `X-Agent: synthesis_agent` header. `BudgetGuard` on the request is a *local safety ceiling*, not billing.

**Immediate mitigation.**
1. Confirm `BudgetGuard` is firing: check `errors` array in the channel-3 frame for `budget_exceeded`.
2. Lower `EXPENSE_AGENT_REQUEST_BUDGET_USD_E5` in the ConfigMap to freeze runaway spend before rollback.
3. If the regression correlates with a synthesis prompt change, revert the offending SHA via the config-repo rollback below.

**Escalation.** Provider-side model regression → open a ticket with the llm-proxy team. Sustained > 10 min at p99 above budget → page the on-call platform lead.

**Rollback trigger.** ≥ 15 % cost regression versus `evals/last_run.json` baseline observed in production; use the CI-verified prior SHA (see rollback rehearsal below).

**Verification.** After rollback, `aws logs filter-log-events --log-group /aws/eks/expense-svc/... --filter-pattern '"cost_usd_e5"'` and confirm the p99 returns to baseline. `curl -sS $POD_IP:8080/readyz` should still report `ready`.

**Known cost gap.** The W7D3 inner Anthropic generation invoked through `retrieve_and_generate` is billed by llm-proxy / CloudWatch, not the local `BudgetGuard`. The rewrite call (`make_query_rewriter`) *is* counted locally. Do not double-count.

---

### Signal 2 — Retrieval p99 above 3-second deadline

**Symptom.** LangSmith runs for `retrieval_agent` end with `deadline_exceeded=true, deadline_limit_s=3.0` and the node returns the sentinel `{"docs": [], "visited_nodes": ["retrieval_agent"], "errors": ["retrieval_deadline_exceeded"]}`. The synthesis node then produces a refusal because `docs` is empty and no tool_result is available.

**Likely causes.** pgvector cold-cache after a rebuild; Redis eviction under memory pressure; BGE reranker warmup latency; slow query rewrite when the retrieval Anthropic client is retrying; DNS/network hiccup between pod and `EXPENSE_AGENT_RAG_POSTGRES_URL` / `EXPENSE_AGENT_REDIS_URL`.

**Dashboard/query.** LangSmith filter `name=retrieval_agent AND metadata.deadline_exceeded=true`. Cross-reference with pgvector RDS/pod CPU + Redis maxmemory-eviction rate.

**Immediate mitigation.**
1. Confirm the sentinel shape reaches synthesis (`errors: ["retrieval_deadline_exceeded"]` — this is the *graceful* refusal path, not a crash).
2. Warm pgvector: `kubectl exec -n expense-svc deploy/expense-agent-svc -- python -c "import psycopg; …"` on a hot-spot query. (Or bounce the pgvector Deployment if it is co-located.)
3. If the reranker (`bge-reranker-base`) is slow to warm, consider setting `EXPENSE_AGENT_RETRIEVAL_DEADLINE_S=5.0` temporarily via the ConfigMap patch; do NOT lower recursion or ceiling.

**Escalation.** Sustained > 5 min at p99 > 3 s → page platform. If ingress-side timeouts (`X-Vercel-AI-Data-Stream: v1` responses dropping) also appear, the SSE bridge is running but the graph is stuck; check checkpointer connectivity next.

**Rollback trigger.** Only if a retrieval-node code change is the correlated cause. The sentinel path is designed to keep the request path alive even during a retrieval outage.

**Verification.** `kubectl logs deploy/expense-agent-svc -n expense-svc | grep 'retrieval_deadline_exceeded'` should return to baseline; a fresh `/v1/chat/stream` POST should complete the two-worker fan-in.

---

### Signal 3 — RAGAS faithfulness seven-day median drop > 0.10

**Symptom.** Production sampler's `ragas_faithfulness` metadata (written to LangSmith runs at `sample_rate=0.01`) shows a > 0.10 drop in the 7-day median.

**Likely causes.** Real answer-quality regression (bad synthesis prompt change, upstream doc corpus drift, retrieval recall drop); evaluator/provider outage returning skewed scores; sampler misconfigured (rate accidentally raised) inflating variance; missing evaluator credentials producing zero-metric writes.

**Dashboard/query.** LangSmith metadata filter `ragas_sampled=true AND ragas_faithfulness < 0.85`, group by `tenant_id` and 24-h buckets. `context_recall` and `answer_relevancy` help disambiguate retrieval-side vs synthesis-side quality drift.

**Immediate mitigation.**
1. Confirm the drop is not a provider artefact: check `ragas_context_recall` and `ragas_answer_relevancy` — a coordinated drop across all three metrics is more likely a real regression; a lonely `faithfulness` drop is often evaluator noise.
2. If the deterministic CI gate remains green (`--gate` in `expense-agent-svc-ci.yml`), the regression is data-side, not code-side.
3. Disable production sampling by setting `EXPENSE_AGENT_RAGAS_SAMPLE_RATE=0.0` in the ConfigMap — this must NOT affect user requests (the sampler is non-blocking; `should_sample()` gating the code path is proven by `test_disabled_sampler_when_no_evaluator`).

**Escalation.** Sustained drop for 48 h → page platform + evaluator-team.

**Rollback trigger.** Correlated code SHA identified as the regression cause; roll back via the config-repo image rollback.

**Verification.** LangSmith 7-day median returns to baseline; deterministic `--gate` remains passing (proves the CI gate stays separate from production sampling by construction).

---

### Signal 4 — AWS BudgetAction fired

**Symptom.** AWS Budgets `expense-agent-svc-monthly` reached 100 % of ACTUAL usage; the `HardCapDenyAction` (`ApprovalModel=AUTOMATIC`, `ActionType=APPLY_IAM_POLICY`) attached the customer-managed DENY policy to `expense-agent-svc-role`. New pods can no longer decrypt secrets / call the LLM path. Pod-side symptom: `RuntimeConfigurationError` at startup or Anthropic 403 mid-request.

**Likely causes.** Sustained cost regression (Signal 1) went unnoticed; per-tenant budget policy not yet in place (Day 60 item); provider price change; abuse traffic.

**Dashboard/query.**
```
aws budgets describe-budget \
  --account-id 726695008378 --budget-name expense-agent-svc-monthly
aws budgets describe-budget-actions-for-budget \
  --account-id 726695008378 --budget-name expense-agent-svc-monthly
aws cloudtrail lookup-events \
  --lookup-attributes AttributeKey=EventName,AttributeValue=AttachRolePolicy \
  --start-time '2026-XX-XX'
```
`iam:AttachRolePolicy` from principal `budgets.amazonaws.com` is the deny attach.

**Immediate mitigation.** *Do not auto-detach.* Manual confirmation is required before removing the hard stop — the point of the BudgetAction is to force a human review. Confirm root cause (Signal 1 or Signal 3). Only then detach:
```
aws iam detach-role-policy \
  --role-name expense-agent-svc-role \
  --policy-arn <DenyPolicyArn>
```
No automatic re-enable path exists.

**Escalation.** BudgetAction firing → immediate page. Any decision to raise the $4 000/month cap requires cost-engineering sign-off.

**Rollback trigger.** If root cause is a code SHA, roll the config-repo overlay to the prior verified SHA (see rehearsal procedure).

**Verification.**
```
aws iam list-attached-role-policies --role-name expense-agent-svc-role
```
DENY policy is absent. Fresh pod rolls; `/readyz` reports `ready`. Fresh `POST /v1/chat/stream` returns a channel-2 frame (not `internal_error`).

---

### Signal 5 — Argo CD OutOfSync or Degraded

**Symptom.** Argo Application `expense-agent-svc` reports `Status: OutOfSync` or `Degraded` in the Argo UI.

**Likely causes.** Deployment failed to become Ready (readonly-root probe issue, missing Secret content, wrong image tag); config-repo overlay was edited outside `_bump-config.yml` and diverged; AppProject destination policy denies `expense-svc` (bootstrap gap); Argo controller not yet aware of the new Application.

**Dashboard/query.**
```
argocd app get expense-agent-svc
argocd app history expense-agent-svc
kubectl -n expense-svc get pods -l app.kubernetes.io/name=expense-agent-svc
kubectl -n expense-svc describe deploy expense-agent-svc
```
The `expense` AppProject is defined in the config repo at `argocd/projects/expense.yaml`; check the `destinations` block includes `expense-svc` on `kubernetes.default.svc`.

**Immediate mitigation.**
1. Confirm the image tag in `expense-agent-svc/overlays/prod/kustomization.yaml` is a real 40-hex SHA — never a floating tag. The prod overlay's `newTag` starts at `"0000000000000000000000000000000000000000"` as a sentinel; the merge-to-main workflow rewrites it via `scripts/bump_config_image.py`.
2. `argocd app diff expense-agent-svc` shows drifted resources; use `argocd app sync expense-agent-svc` only after root-cause is understood.
3. If deployment is Degraded, `kubectl -n expense-svc logs deploy/expense-agent-svc --tail=200` and grep for `RuntimeConfigurationError` (fail-closed startup) or CrashLoopBackOff.

**Escalation.** > 10 min OutOfSync/Degraded and user impact confirmed → page platform.

**Rollback trigger.** Bad SHA merged into the config repo overlay.

**Verification.** `argocd app get expense-agent-svc` returns `Synced/Healthy`; `kubectl -n expense-svc rollout status deploy/expense-agent-svc` reports success; new pod images match the intended SHA.

---

## Troubleshooting

### 1. Service not ready (`/readyz` returns 503)

`/readyz` reports `not_ready` until every component in `runtime.AgentRuntime.ready` flips to `True`. The order is:
1. `postgres_checkpointer` — `AsyncPostgresSaver.from_conn_string(...)` + `saver.setup()`.
2. `rag_pool` + `redis` — pgvector `psycopg_pool.ConnectionPool` and Redis client opened.
3. `mcp_session` — `sse_client(EXPENSE_AGENT_MCP_SSE_URL, headers=...)` + `ClientSession.initialize()`.
4. `graph` — `build_expense_agent_graph(nodes=..., checkpointer=saver)`.

If `postgres_checkpointer` never becomes `True`, check that `EXPENSE_AGENT_POSTGRES_URL` (checkpointer) and `EXPENSE_AGENT_RAG_POSTGRES_URL` (pgvector) are pointing at their *distinct* stores. See settings.py — the two DSNs are intentionally different (5432 vs 55432 in the local layout).

### 2. MCP authentication failure

`RuntimeConfigurationError` at startup with `EXPENSE_AGENT_MCP_BEARER_JWT` in the message means the fail-closed check refused to open the SSE transport. If the token is present but the SSE handshake fails, the W7D4 middleware verifies JWT signature (JWKS), expiry (`exp`), and audience. Rotate the token, confirm the JWKS URL is reachable from the pod, and confirm the audience claim matches `EXPENSE_MCP_JWT_AUDIENCE` on the MCP server side.

**Never log the bearer.** `sse.py` maps context-missing failures to `request_context_unavailable`; MCP transport failures surface as `internal_error` — the token value never appears in any error frame.

### 3. Checkpoint / resume problems

Every request carries a `thread_id` (either client-supplied or generated by the route). LangGraph 1.2 keys checkpoints on `configurable.thread_id`; `invocation_config(thread_id)` is the *only* place the runtime config is built. If a resumed thread carries a stale `request_id`, `dependencies.get_request_context_for_state(state)` raises `RequestContextUnavailable`, which the SSE bridge maps to a safe channel-3 frame.

Postgres checkpoint tables:
```
psql "$EXPENSE_AGENT_POSTGRES_URL" -c '\d checkpoints'
psql "$EXPENSE_AGENT_POSTGRES_URL" -c "SELECT thread_id, checkpoint_id FROM checkpoints ORDER BY checkpoint_id DESC LIMIT 20;"
```

**Never** put a runtime client / MCP session / BudgetGuard into `AgentState`. Enforced by `test_agent_state_annotation_stays_serialisable`.

### 4. `BudgetExceeded`

Emitted from `BudgetGuard.check_or_raise()` or `add_cost()` when spend reaches or exceeds `ceiling_usd_e5=25000` for the request. The SSE bridge maps this to `channel 3: "budget_exceeded"`. Pre-stream the route returns `503` + `Retry-After: 5`; mid-stream the channel-3 frame is emitted before the connection closes.

**Per-request isolation.** Each `POST /v1/chat/stream` constructs its own `BudgetGuard` (verified by `test_concurrent_requests_get_isolated_budget_guards`). Two requests never share a guard.

### 5. `GraphRecursionError`

Raised by LangGraph when the invocation exceeds `recursion_limit=25`. The production graph has no feedback edge today; a `GraphRecursionError` in prod is a symptom of misconfigured routing (extra worker slot added without base-case guard) or a future HITL loop that regresses. The SSE bridge maps this to `channel 3: "recursion_limit"`. Future HITL loops must include an explicit exit condition; the AST guardrail test `test_every_graph_invoke_call_site_uses_invocation_config` prevents a call site from silently omitting the limit.

### 6. Incorrect tenant data / cross-tenant contamination

`get_request_context_for_state` refuses when the state's `tenant_id` does not match the registered `RequestContext.tenant_id` (`RequestContextMismatch`). The API node forces `tenant_id` from the request context on every `orders.*` tool call (`_prepare_tool_arguments`), overriding any model-supplied value. Deterministic idempotency keys are UUID v5 over `(thread_id, tool_name, canonical_args_hash)` — a different tenant produces a different key, so accidental replay across tenants cannot land on the same idempotency slot.

### 7. Frontend streaming problems

Backend response headers must include exactly:
```
Content-Type: text/plain; charset=utf-8
X-Vercel-AI-Data-Stream: v1
Cache-Control: no-cache
X-Thread-Id: <opaque>
X-Request-Id: <opaque>
```
Wire frames:
- `0:<json string>\n` — synthesis text delta (`useChat.messages[-1].content`).
- `2:<json array>\n` — one-element array wrapping `FinalAnswer` (`useChat.data`).
- `3:<json string>\n` — error code slug (`useChat.error.message`).

The AgentChatPanel reuses the server-supplied `X-Thread-Id` on subsequent turns via `onResponse` — proven by `test_retains_the_server_X_Thread_Id_on_the_second_turn`.

---

## Deployment prerequisites

Before the first successful production deployment, all of these must be in place:

1. **ECR repository** `726695008378.dkr.ecr.us-east-1.amazonaws.com/expense-agent-svc` provisioned (not created by CI). `scripts/ecr_preflight.sh` fails loudly when absent.
2. **AWS validation role** — repo variable `EXPENSE_AGENT_AWS_VALIDATION_ROLE_ARN` configured with an OIDC role authorised for `cloudformation:ValidateTemplate` in account 726695008378.
3. **AWS deploy role** — repo variable `EXPENSE_AGENT_DEPLOY_ROLE_ARN` with `ecr:GetAuthorizationToken`, `ecr:BatchCheckLayerAvailability`, `ecr:PutImage` on the expense-agent-svc repo.
4. **GitOps token** — `secrets.GITOPS_REPO_TOKEN` fine-grained PAT scoped to the config repo (`contents: write`, `pull-requests: write`).
5. **Anthropic evaluator secret** — `secrets.ANTHROPIC_API_KEY` for the `external-eval` job.
6. **LangSmith secret** — `secrets.LANGSMITH_API_KEY` (optional but recommended for CI tracing).
7. **Config repo AppProject** — extend `argocd/projects/expense.yaml` `destinations:` to include `expense-svc` on `kubernetes.default.svc`.
8. **Config repo overlay** — first-time bootstrap: `scripts/bump_config_image.py --allow-bootstrap --bootstrap-template …/expense-agent-svc/gitops/overlays/prod` copies the committed template into `<config-repo>/expense-agent-svc/overlays/prod/`.
9. **Argo Application** — apply `expense-agent-svc/argo-apps/expense-agent-svc.yaml` to the target Argo instance.
10. **BudgetAction stack** — deploy `expense-agent-svc/cfn/agent-svc-budget.yaml` with the customer-managed `DenyPolicyArn` supplied.

---

## Operational commands

```
# Inspect the local Docker image (built by CI as :${{ github.sha }})
docker image inspect expense-agent-svc:w7d5

# Verify the pushed digest for a given SHA
aws ecr describe-images \
  --repository-name expense-agent-svc \
  --image-ids imageTag=<sha> \
  --region us-east-1 --profile uptimecrew

# Pod status
kubectl -n expense-svc rollout status deploy/expense-agent-svc
kubectl -n expense-svc logs deploy/expense-agent-svc --tail=200
kubectl -n expense-svc describe deploy expense-agent-svc

# Argo state
argocd app get expense-agent-svc
argocd app history expense-agent-svc

# Kustomize render (locally reproduces what Argo applies)
kubectl kustomize expense-agent-svc/gitops/overlays/prod

# CloudFormation Budget stack
aws cloudformation describe-stacks \
  --stack-name expense-agent-svc-budget \
  --region us-east-1 --profile uptimecrew

# Budgets state
aws budgets describe-budget \
  --account-id 726695008378 --budget-name expense-agent-svc-monthly
aws budgets describe-budget-actions-for-budget \
  --account-id 726695008378 --budget-name expense-agent-svc-monthly

# Config-repo rollback: revert the image bump commit
git -C <config-repo> revert <bad-bump-sha>
git -C <config-repo> push origin main
# Argo auto-syncs to the reverted overlay.
```

---

## Rollback rehearsal

**Status: Pending real Argo CD login and production deployment.**

| Field | Value |
|---|---|
| SHA reverted | PENDING |
| Prior SHA restored | PENDING |
| Rehearsal start (UTC) | PENDING |
| Argo sync completion (UTC) | PENDING |
| Wall-clock duration | PENDING |
| Application health result | PENDING |
| Verified pod image | PENDING |
| Verified pod labels | PENDING |

### Exact blockers

- Argo CD CLI installed locally but not logged into any server (`argocd login <server>` never run).
- `expense-svc` is not yet a permitted destination in the config-repo `expense` AppProject (`argocd/projects/expense.yaml destinations:` lacks that entry).
- The config-repo path `expense-agent-svc/overlays/prod` does not yet exist — first-time bootstrap has not run.
- ECR repository `expense-agent-svc` is not provisioned in account `726695008378`.
- No image has been pushed to ECR.
- The `Application expense-agent-svc` has never been applied to any Argo instance.

### Future rehearsal procedure

Once every blocker above is cleared, run:

1. **Capture current config-repo image SHA.**
   ```
   git -C <config-repo> log -1 --format=%H expense-agent-svc/overlays/prod/kustomization.yaml
   ```
2. **Merge a test SHA bump.** Trigger the `bump-config` job by pushing to `main` in this repo (or manually run `_bump-config.yml` with a known-good SHA).
3. **Wait for Argo Synced/Healthy.**
   ```
   argocd app wait expense-agent-svc --sync --health --timeout 600
   ```
4. **Record pod images/labels.**
   ```
   kubectl -n expense-svc get pods -l app.kubernetes.io/name=expense-agent-svc -o wide
   kubectl -n expense-svc get deploy expense-agent-svc -o jsonpath='{.spec.template.spec.containers[0].image}'
   ```
5. **Revert the config-repo image commit.**
   ```
   git -C <config-repo> revert <bump-sha>
   git -C <config-repo> push origin main
   ```
6. **Watch Argo auto-sync** — automated + selfHeal already true, so no manual sync needed. Confirm `argocd app get expense-agent-svc` returns to Synced.
7. **Verify the prior image is restored.** Re-run the `kubectl get deploy ... -o jsonpath` command and confirm the digest matches the captured "prior SHA".
8. **Roll forward again** by reverting the revert (`git revert <revert-sha>`) once the incident is closed.
9. **Fill in the PENDING table above** with actual observed values.

**Do not** claim this rehearsal occurred until every field is populated with real captured output.

---

## 30 / 60 / 90 day plan

### Day 30 — production hardening
- Provision ECR repository + `expense-agent-svc-role` + the two OIDC roles.
- Deploy `expense-agent-svc-budget` CloudFormation stack (with real `DenyPolicyArn`).
- Extend the config-repo `expense` AppProject destinations to include `expense-svc`.
- Bootstrap the config-repo `expense-agent-svc/overlays/prod/` path.
- Deploy the Argo Application; observe first `Synced/Healthy`.
- Execute the rollback rehearsal above and populate the PENDING fields.
- Tune `EXPENSE_AGENT_{RETRIEVAL,API,SYNTHESIS}_DEADLINE_S` from observed p95/p99.
- Remove the `runtime.py` coverage omission only when live integration coverage is genuinely available (real MCP + Anthropic + Postgres simultaneously).
- Add JWT/JWKS rotation monitoring to the on-call rotation.
- Draft an evaluator provider-cap runbook (what happens when Anthropic returns 429 to the RAGAS gate).

### Day 60 — scope expansion
- Publish additional MCP tools (refunds analytics, dispute lookup) from the W7D4 server.
- Add a supervisor-driven approval / HITL flow for `orders.create_refund` writes (the supervisor's docstring already names this as its future policy home).
- Expand `evals/scenarios.jsonl` from 20 to ~40 scenarios; add adversarial rows.
- Introduce per-tenant rate policies at the supervisor (rejection frames in channel 3 with a `rate_limited` code — extends the `SAFE_ERROR_MESSAGES` catalogue).
- Improve W7D3 inner-generation cost accounting so the retrieval node reports the full grounded spend (currently only the rewrite call is counted locally; llm-proxy / CloudWatch remains authoritative).
- Add frontend trace links (LangSmith run URL surfaced in the final answer aside, dev-only).

### Day 90 — scale and isolation
- Multi-region: replicate the pgvector store + checkpointer; deploy the agent in `us-west-2` as well.
- Tenant-isolated worker pools: run one pod pool per tenant tier; use the supervisor's per-tenant rate hook to route.
- Regional checkpoint stores: per-region PostgresSaver DSNs so a regional outage does not lose thread state globally.
- Cross-region failover testing: deliberately fail `us-east-1`, verify the streaming path shifts.
- Tenant-specific budgets: split the $4 000/month cap into per-tenant sub-budgets (one BudgetAction per tenant).
- Cross-region GitOps promotion: extend the config-repo overlay tree with regional variants.
- Chaos and recovery rehearsal: fault-inject at each of the five signals above; measure MTTD/MTTR against the SLO.
