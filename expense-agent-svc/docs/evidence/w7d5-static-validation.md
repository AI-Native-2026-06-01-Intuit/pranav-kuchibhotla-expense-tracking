# W7D5 static validation evidence

## Header

| Field | Value |
|---|---|
| Branch | `w7d5-implementation` |
| Base commit (main tip) | `2a8cc4f` |
| Batches | 8 checkpointed Claude Code sessions |
| Commit count on branch | 13 W7D5 commits + 1 merge base |

## Full W7D5 commit list

```
72cbba3 ci(agent):    add final capstone quality and deployment gates
7c1e9cf deploy(agent): add Docker GitOps and budget templates
26a2372 test(agent):   add trajectory faithfulness and cost gates
7767f59 feat(agent):   add production RAGAS sampling and query rewrite
6f2cccd feat(web):     connect chat UI to agent data stream
932fa8d feat(agent):   wire production model and retrieval adapters
14dc63e feat(agent):   add request-scoped AI SDK streaming
c9c0e1d feat(agent):   add FastAPI lifespan and runtime ownership
fd57ae9 test(agent):   prove Postgres checkpoint resume and recursion limits
7604578 feat(agent):   add supervisor graph and runtime recursion config
2eadbd8 feat(agent):   add budgets deadlines and worker nodes
de0878f feat(mcp):     accept deterministic UUID5 idempotency keys
4b608d1 feat(agent):   scaffold service with typed state and runtime dependencies
2a8cc4f (base)         Merge pull request #18 from AI-Native-2026-06-01-Intuit/w7d4-implementation
```

## Project layout

```
expense-agent-svc/
├── src/expense_agent_svc/
│   ├── app.py                 FastAPI factory + lifespan + /v1/chat/stream
│   ├── budgets.py             BudgetGuard (integer money, request-scoped)
│   ├── dependencies.py        AgentDependencies + RequestContext registry
│   ├── graph.py               StateGraph + supervisor + invocation_config
│   ├── runtime.py             AsyncExitStack-owned production runtime
│   ├── sampling.py            ProductionSampler + GroundedSample
│   ├── settings.py            EXPENSE_AGENT_-prefixed pydantic-settings
│   ├── sse.py                 AI SDK v4 data-stream bridge
│   ├── state.py               AgentState TypedDict + reducers
│   ├── nodes/
│   │   ├── _deadline.py       async deadline decorator + sentinel
│   │   ├── api.py             API worker + MCP dynamic discovery + UUID5
│   │   ├── retrieval.py       thin adapter over W7D3 retrieve_and_generate
│   │   └── synthesis.py       Instructor FinalAnswer + refusal path
│   └── scripts/
│       └── eval.py            trajectory + cost + external-RAGAS CLI
├── evals/
│   ├── scenarios.jsonl        exactly 20 committed trajectory rows
│   ├── trajectory.py          ordered matcher (both-worker order-agnostic)
│   └── last_run.json          deterministic-fixture baseline (faithfulness: null)
├── argo-apps/expense-agent-svc.yaml    Argo Application (points at real config repo)
├── gitops/
│   ├── base/                  Deployment + Service + ConfigMap + placeholder Secret + kustomization
│   └── overlays/prod/         namespace=expense-svc, replicas=3, image newTag placeholder
├── cfn/agent-svc-budget.yaml  AWS::Budgets::Budget + BudgetsAction (APPLY_IAM_POLICY DENY)
├── scripts/
│   ├── bump_config_image.py   config-repo image bump with --allow-bootstrap
│   └── ecr_preflight.sh       fail-closed describe-repositories
├── Dockerfile
├── Dockerfile.dockerignore
├── RUNBOOK.md
├── PROMPT_JOURNAL.md
└── tests/                     280 tests, coverage 85.20%
```

## Architecture summary

Three-node LangGraph 1.2 supervisor. The supervisor emits `list[Send]`
so parallel dispatch fans out to `retrieval_agent` + `api_agent` in the
same super-step; both worker edges land on `synthesis_agent` for a
single-execution fan-in join (proven by counter-based test). Every
non-serialisable dependency (MCP session, three AsyncAnthropic
clients, one sync retrieval client, pgvector `ConnectionPool`, Redis,
Instructor wrapper, `AsyncPostgresSaver`) is owned by the FastAPI
lifespan's `AsyncExitStack` and injected through
`AgentDependencies`. `AgentState` carries only JSON-serialisable
scalars + reducer-annotated collections; nodes resolve their live
`BudgetGuard` through the per-request `RequestContext` registry keyed
by an opaque `request_id`.

## Installed API adaptations

| Contract | Installed | Adaptation |
|---|---|---|
| `StateGraph.compile(recursion_limit=…)` | Not accepted in LangGraph 1.2.9 | `recursion_limit` is runtime `configurable`; one central `invocation_config(thread_id)` builds the config. AST-based test enforces every `.invoke/.ainvoke/.astream_events` call site uses it. |
| `AsyncPostgresSaver.from_conn_string` | `@asynccontextmanager` yielding a saver whose connection dies with the CM | FastAPI lifespan holds it inside `AsyncExitStack`; graph is compiled with the live saver. Restart-resume test is a controlled `async with` exit + reopen, documented as a deterministic simulation. |
| `mcp.ClientSession.call_tool(headers=…)` | No `headers` parameter | UUID5 idempotency key goes into the tool `arguments` dict; the W7D4 MCP server forwards it as the upstream HTTP `Idempotency-Key` header. |
| W7D4 `CreateRefundArgs.idempotency_key: UUID v4-only` | Deterministic UUID5 would be rejected | `feat(mcp): accept deterministic UUID5 idempotency keys` — v4 and v5 accepted; v1/v2/v3 still rejected. Five new schema tests. |
| Instructor 1.15.4 async | `AsyncInstructor.messages.create_with_completion` returns `(parsed, raw_completion)` | Production synthesizer uses it to capture `raw_completion.usage` for real per-request cost; fake-friendly `create` path preserved for tests. |
| AI SDK v4 wire grammar | channel 2 needs JSON *array*, channel 3 needs JSON *string* | Backend `_final_frame` emits `2:[{payload}]`; `_error_frame` emits `3:"code_slug"`. Frontend resolves the human error text from a local `SAFE_ERROR_MESSAGES` catalogue — no exception repr on the wire. |

## Proofs

### State reducer proof

`test_state_reducers.py` inspects `typing.get_type_hints(AgentState,
include_extras=True)` and asserts every reducer identity:
`operator.add` on `docs`, `cost_usd_e5`, `visited_nodes`, `errors`;
`add_messages` on `messages`; `_merge_tool_results` (custom, preserves
earlier writes on key collision) on `tool_results`. Parallel-branch
merge preservation tested with two sibling dicts.

### Supervisor / fan-in proof

`test_graph_compile.py::test_both_flow_preserves_reducers_and_runs_synthesis_once`
routes a combined prompt through the compiled graph with counter fakes:
```
counter["retrieval_agent"] == 1
counter["api_agent"]      == 1
counter["synthesis_agent"] == 1     # exactly once, even with two upstreams
result["answer"] == "docs=1 tools=1"
```
`visited_nodes` reducer accumulates all three names on the both-branch.

### Postgres restart/resume proof

`tests/test_checkpointer_resume.py`, run live against
`postgresql://postgres:postgres@localhost:5432/postgres` (docker
container `w7d5-postgres`):

- `test_setup_is_idempotent_across_two_savers` — passes; the reopened
  saver reads the prior thread's `answer`.
- `test_state_survives_saver_restart_simulation` — passes; after
  fully closing the first saver's async context and opening a new
  one on the same DSN, `graph.aget_state(invocation_config(thread_id))`
  returns a `StateSnapshot` whose `docs`, `tool_results`, `visited_nodes`,
  and `answer` all match the pre-"restart" values.
- `test_checkpoint_row_contains_only_serialisable_state` — walks the
  restored state values and asserts none are callable, none are
  `asyncio.*` primitives, none are `psycopg.*` connections.
- `test_setup_is_idempotent_across_two_savers` — proves a second
  `saver.setup()` on the same DSN does not truncate prior checkpoint
  rows.

Documented in the test as a *deterministic restart simulation*, not a
real Kubernetes pod kill.

### Recursion-limit proof

`test_recursion_limit.py`:
- `test_synthetic_loop_raises_at_configured_limit` — a test-only
  self-looping graph raises `GraphRecursionError` in bounded
  wall-clock time when invoked through `invocation_config`.
- `test_invocation_config_recursion_limit_is_twenty_five` —
  `DEFAULT_RECURSION_LIMIT == 25` and the returned config carries
  `recursion_limit=25`.
- `test_every_graph_invoke_call_site_uses_invocation_config` — AST
  walker over `src/**/*.py` asserts every `.invoke/.ainvoke/.astream_events`
  method call sits in a module that also imports `invocation_config`.
- `test_production_graph_has_no_artificial_feedback_loop` —
  introspects the compiled graph's edge list; no self-loop, no
  `synthesis_agent → worker` back-edge.

### Deadline proof

`test_deadline.py`: slow node returns the fresh sentinel copy within a
bounded wall-clock (<0.5 s for a 0.05 s deadline); fast node returns
its own result unchanged; non-`TimeoutError` propagates;
`functools.wraps` preserves `__name__` and `__doc__`; injected metadata
tagger receives `deadline_exceeded=True, deadline_limit_s=<float>,
node=<name>`. Sentinel copies are independent — mutating one does not
affect the other.

### Request budget proof

`test_budget_guard.py`: exact-ceiling raise records spend before
raising; float and bool cost rejected; negative rejected; zero
accepted; `record_usage(tokens, rate)` uses integer `//`. `test_app.py::
test_concurrent_requests_get_isolated_budget_guards` sends two
`/v1/chat/stream` POSTs and captures each request's live budget
through the registry — asserts `id(budget)` differs, proving
per-request isolation.

### MCP discovery + UUID5 proof

`test_api_node.py`:
- `test_api_node_calls_list_tools_and_translates_catalogue` — no
  hardcoded catalogue; `session.list_tools()` is invoked; the
  Anthropic tool-use schema is derived from `Tool.inputSchema`.
- `test_deterministic_key_is_uuid5_and_repeats` — same
  `(thread_id, tool_name, canonical_args_hash)` → same UUID with
  `version == 5`.
- `test_deterministic_key_changes_with_thread_tool_or_args` — sensitive
  to each input.
- `test_api_node_forces_tenant_and_injects_uuid5` — model-supplied
  `tenant_id="tenant-b"` is overwritten by request `tenant-a`; the
  model's attacker-picked `idempotency_key` is replaced by the
  deterministic UUID5 before `call_tool`.
- `test_api_node_read_only_tool_gets_no_idempotency_key` — read tools
  never receive an idempotency key.
- `test_api_node_caps_iterations_at_max` — five-iteration cap.

### Instructor / refusal proof

`test_synthesis_node.py`:
- `test_empty_context_refuses_without_invoking_model` — empty docs +
  empty tool_results returns `confidence < 0.4`, `citations == []`,
  and the fake Instructor client is never called.
- `test_nonempty_context_invokes_instructor_with_correct_kwargs` —
  `response_model=FinalAnswer`, `max_retries=2`, model equals
  `settings.model_name`.
- `test_default_synthesizer_records_real_usage_via_budget` — real
  usage-aware synthesizer with `raw_completion.usage.input_tokens=
  1_000_000, output_tokens=500_000` at rates 300/1500 per-M records
  `cost == 300 + 750 == 1050`, and `guard.spent_usd_e5 == 1050`.
- `test_default_synthesizer_zero_cost_when_usage_missing` — missing
  `usage` → zero cost, no fabrication.
- `test_no_pydantic_leak_in_state` — no `Citation` / `FinalAnswer`
  pydantic instances leak into state; only JSON dumps.

### Stream protocol proof

`test_sse.py` (19 tests):
- Channel 0 fired only for `metadata.langgraph_node == "synthesis_agent"`.
- Fallback text emitted once on channel 0 before channel 2 when the
  synthesis path produced no chat-model deltas (Instructor structured
  output does not stream tokens).
- Channel 2 emitted exactly once; payload wrapped in a JSON array;
  malformed payloads are coerced through `_normalise_final_answer`.
- Channel 3 mapping: `GraphRecursionError→"recursion_limit"`,
  `BudgetExceeded→"budget_exceeded"`, `RequestContextUnavailable/
  Mismatch→"request_context_unavailable"`, generic→`"internal_error"`.
- `asyncio.CancelledError` propagates; never converted to a
  channel-3 frame.
- Secret-leak test seeds `RuntimeError("secretpwd sk-ant-XYZ eyJhaZ.jwt")`
  and asserts none of those substrings appear on the wire.

### Frontend proof

`expense-web/src/test/AgentChatPanel.test.tsx` (8 tests): request URL
uses `VITE_EXPENSE_AGENT_URL`; body contains `question` + `tenant_id`
+ `thread_id` (no `request_id`, no `authorization`); server-supplied
`X-Thread-Id` is reused on turn 2; channel-0 text renders once;
channel-2 FinalAnswer surfaces `Confidence: 0.82` and citation list;
channel-3 error slug is looked up in the safe catalogue (the raw slug
never appears in user-visible text); malformed channel-2 payload is
rejected by `asAgentFinalAnswer` and does not crash the render;
tenant selection is client-controlled and cannot be overwritten by
the agent response.

### Production sampler proof

`test_sampling.py` (21 tests): sample-rate boundaries (0 never,
1 always, deterministic fractional via injected `random_source`); non-
blocking (`submit` returns in < 30 ms while a `delay=0.05` evaluator
runs, `aclose()` awaits completion); evaluator failure swallowed —
writer not called; non-numeric metric values → no write (no fabrication);
disabled sampler is a no-op; empty-context samples never reach the
evaluator; three required metric names (`ragas_faithfulness`,
`ragas_context_recall`, `ragas_answer_relevancy`).

### Trajectory gate proof

`tests/test_trajectory_eval.py` (28 tests) + live CLI:

```
uv run python -m expense_agent_svc.scripts.eval --gate
scenarios: 20
trajectory: mean=1.00 floor=0.70 pass=True
answer:     mean=1.00 floor=0.70 pass=True
cost:       current=142.50 baseline=142.50 regression=+0.00% max=15.00% pass=True
```

Ordered semantics enforced: synthesis-before-worker rejected, duplicate
synthesis rejected, missing worker rejected, foreign node rejected.
Both-branch order-agnostic between the two workers. Exactly-20 rows;
duplicate qid rejected; wrong count rejected; unknown tenant rejected;
unknown node rejected. Baseline label:
`"source": "deterministic_fixture"`. Baseline never overwritten by a
gate run.

External path:
```
EXPENSE_AGENT_ALLOW_EXTERNAL_EVAL_SKIP=1 \
  uv run python -m expense_agent_svc.scripts.eval --gate --external
ragas: external RAGAS skipped (external RAGAS skipped — ANTHROPIC_API_KEY missing and EXPENSE_AGENT_ALLOW_EXTERNAL_EVAL_SKIP=1 set)
```
`status="skipped"`, `faithfulness=null` (never a fabricated number).
CI never exports the skip flag.

### Deployment artifact proof

`tests/test_deployment_artifacts.py` (33 tests): Dockerfile shape,
non-root uid 65532, EXPOSE 8080, HEALTHCHECK present, no secrets, no
`.env` copied; GitOps base + prod overlay YAML shape; Argo Application
`namespace: expense-svc`, `project: expense`, real config-repo
remote, `path: expense-agent-svc/overlays/prod`, `prune=true`,
`selfHeal=true`; CFN Budget monthly $4000, BudgetsAction
`ApprovalModel=AUTOMATIC` / `ActionType=APPLY_IAM_POLICY` / threshold
100 percent ACTUAL / target role `expense-agent-svc-role`; ECR
preflight message shape; `bump_config_image.py` rejects bad SHAs, refuses
to edit outside `expense-agent-svc/`, refuses on multiple image
matches, supports `--allow-bootstrap` into empty target; local config
repo `git status --porcelain` empty at test time.

### CI workflow proof

`tests/test_ci_workflow.py` (19 tests): workflow name matches; PR +
main triggers with path filters; every `uses:` reference is a
40-char SHA (no `@vN`, no `@main`); Postgres 16 service present;
`uv sync --frozen`; ruff + `ruff format --check`; strict mypy on
`src/ tests/ evals/`; `--cov-fail-under=85`; deterministic gate
present without `EXPENSE_AGENT_ALLOW_EXTERNAL_EVAL_SKIP` (comments
excluded); external gate with `--external`; frontend
`npm ci`+test+typecheck+lint+build; Docker `context: .`,
`file: expense-agent-svc/Dockerfile`; account 726695008378; no
`123456789012`; no `:latest`; ECR preflight step present;
`bump-config` needs `build-and-push`; merge job restricted to main
push; `id-token: write` on AWS jobs; `aws cloudformation
validate-template`; no `cloudformation deploy` / `create-stack` /
`update-stack` / `argocd app sync` / `argocd app create` / non-dry-run
`kubectl apply` / secret literals.

## Final observed results

### Agent test suite
- **280 passed** (Python)
- Coverage **85.20 %** (85 % floor)
- Ruff clean
- `ruff format --check` clean
- `mypy --strict src/ tests/ evals/` clean
- `uv build`: produces sdist + wheel

### Deterministic evaluation
- 20 scenarios
- trajectory mean **1.00** (floor 0.70)
- answer-substring mean **1.00** (floor 0.70)
- cost regression **+0.00 %** (max 15 %)

### External RAGAS
- **Skipped / not_measured** locally because no evaluator key was
  supplied and `EXPENSE_AGENT_ALLOW_EXTERNAL_EVAL_SKIP=1` was
  explicitly enabled. `faithfulness: null` in the JSON report.

### Frontend
- **77 passed** (17 files)
- Typecheck green
- ESLint: 0 errors / 4 warnings (pre-existing, non-blocking)
- `vite build` green (chunk-size advisory unchanged)

### W7D4 regression (expense-mcp-server)
- 82 passed
- 1 honest Docker E2E skip (image not built locally)
- Ruff / strict mypy green

### W7D3 regression (expense-ai)
- 105 passed
- 2 honest external-evaluator skips
- Ruff / strict mypy green

### Postgres integration
- **4 passed** (`test_checkpointer_resume.py`) live against
  `w7d5-postgres`

### Docker
- `docker build -f expense-agent-svc/Dockerfile -t expense-agent-svc:w7d5 .` **succeeded**
- `docker run --rm --entrypoint python expense-agent-svc:w7d5 -c "from expense_agent_svc.app import create_app; print('agent image import ok')"` **succeeded**
- Non-root uid **65532**
- Port **8080** exposed
- HEALTHCHECK present

### Kustomize render + kubectl client dry-run
- `kustomize build expense-agent-svc/gitops/overlays/prod` **succeeded**
- `kubectl apply --dry-run=client` **succeeded** (ConfigMap, Secret, Service, Deployment)

### CloudFormation
- `aws cloudformation validate-template --template-body file://expense-agent-svc/cfn/agent-svc-budget.yaml --profile uptimecrew --region us-east-1` **succeeded**

## Infrastructure gaps (exact, not turned into checkmarks)

- **No GitHub Actions run** — the workflow was committed but has never
  fired against Actions.
- **No ECR repository** provisioned in account 726695008378 for
  `expense-agent-svc`.
- **No image push** to ECR.
- **No Argo login** — `argocd login <server>` never executed.
- **No Application deployment** — `argocd app create/apply` never
  executed.
- **No Argo Synced/Healthy result** observed.
- **No rollback rehearsal** completed — the runbook explicitly marks
  every field of that record `PENDING`.
- **Config repo does not yet contain agent overlay** — the path
  `expense-agent-svc/overlays/prod/` does not exist in the local
  clone of the config repo.
- **AppProject does not yet allow `expense-svc`** — the config-repo
  `argocd/projects/expense.yaml` `destinations:` block lists
  `expense-{dev,staging,prod}` only.
- **BudgetAction stack not deployed** — CloudFormation stack
  `expense-agent-svc-budget` does not exist in the AWS account.

## Guardrail scan results

```
grep -RIn "MemorySaver" expense-agent-svc/src                             → clean
grep -RIn "except:" expense-agent-svc/{src,tests,evals}                   → clean
grep -RIn "sk-ant-|lsv2_pt_|eyJhbGciOi" expense-agent-svc + workflow      → only test fixtures asserting redaction / no-leak
grep -RIn "123456789012" expense-agent-svc + workflow                     → only inside "not in text" test assertions
grep -RIn "uses:.*@v[0-9]|uses:.*@main" workflow                          → none
grep -RIn ":latest|/latest" gitops + workflow                             → only in comments explaining "never :latest"
grep -RIn "argocd app sync|cloudformation deploy|create-stack|ecr create-repository" → only inside test assertions
grep -RIn '"faithfulness":\s*[0-9]' evals/last_run.json                    → clean (value is null)
git -C ~/Documents/pranav-kuchibhotla-expense-config status --porcelain    → empty
```

## Final deliverable checklist

Locally verified in this branch:

- [x] New uv project
- [x] path dependencies (expense-ai, expense-mcp-server)
- [x] uv.lock committed
- [x] typed state reducers
- [x] supervisor list[Send]
- [x] three graph nodes
- [x] parallel fan-in (exactly-once synthesis)
- [x] PostgresSaver wired inside AsyncExitStack
- [x] restart/resume proof (4 live tests)
- [x] deadlines (3s retrieval, 5s API, 8s synthesis)
- [x] recursion limit (invocation_config, AST-checked call sites)
- [x] request budget (25000 cost_usd_e5, per-request isolation)
- [x] Instructor FinalAnswer (extra="forbid", max_retries=2)
- [x] refusal path (empty context, confidence<0.4, no model call)
- [x] MCP discovery (list_tools + tool_schema translation)
- [x] deterministic UUID5 writes
- [x] AI SDK v4 stream (0:/2:/3:)
- [x] React integration (AgentChatPanel + 8 tests)
- [x] production RAGAS sampler
- [x] 20-row deterministic gate
- [x] cost regression gate
- [x] Docker image (built, imported, non-root)
- [x] GitOps manifests
- [x] Argo Application manifest
- [x] BudgetAction template
- [x] CI workflow
- [x] Runbook
- [x] 30/60/90 plan
- [x] Prompt journal
- [x] AI deviations (>=6, in PYTHON.md)
- [x] no plaintext secrets

Not yet done (require real infrastructure or a GitHub Actions run):

- [ ] External RAGAS measured at >=0.85 on this branch
- [ ] Green expense-agent-svc-ci Actions URL
- [ ] ECR repository provisioned
- [ ] Image pushed
- [ ] Config-repo agent overlay merged
- [ ] Argo Application deployed
- [ ] Argo Synced/Healthy observed
- [ ] BudgetAction stack CREATE_COMPLETE
- [ ] Real rollback rehearsal completed
