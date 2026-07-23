# expense-agent-svc — Prompt journal

Real prompts and faithful response summaries from the Claude Code session
that produced W7D5. The work was **intentionally split into 8 checkpointed
Claude Code batches** rather than one uninterrupted pass — the user
explicitly scoped every batch, reviewed the report between batches, and
green-lit the next. The commit list on `w7d5-implementation` (13 commits)
matches the batch cadence.

Every "raw response excerpt" below is a faithful paraphrase of my
in-session output at the corresponding step — not a fabricated quote. The
actual code that landed is in-tree and can be diffed against these
summaries.

---

## Entry 1 — Three-node graph, supervisor, and reducers

**Batch.** Phases 6–11 (2026-07-22).

**Prompt (user, verbatim excerpts).**
> Proceed with W7D5 Phases 6–11 only. […] Do not: put clients, sessions,
> connections, callables, or BudgetGuard objects in AgentState.
> […] Implement the required production topology: StateGraph[AgentState],
> three named nodes […] supervisor returns list[Send] […] parallel
> workers converge on synthesis. […] Inspect the installed LangGraph
> 1.2.9 behavior and implement the correct fan-in topology so […] both
> runs both workers then exactly one synthesis […] `recursion_limit` is
> a runtime invocation configuration in current LangGraph versions. If
> compile() does not accept it, do not pass an invalid argument.

**Raw response excerpt (paraphrased).**
> `StateGraph.compile()` in installed langgraph 1.2.9 does NOT accept
> `recursion_limit`. It is invocation-time only. Confirmed by inspecting
> `inspect.signature(StateGraph.compile)`. I'm introducing one central
> helper `invocation_config(thread_id)` and an AST-based test that walks
> every `.invoke/.ainvoke/.astream(_events)` call site in `src/` and
> asserts the file also imports `invocation_config`. Both worker edges
> going to `synthesis_agent` via `add_edge` produce a natural fan-in
> join in LangGraph 1.2 — I verified synthesis executes exactly once
> even on the both-branch by driving the compiled graph with counter
> fakes.

**Verdict.** **Used as is** — the AST walker is now
`tests/test_recursion_limit.py::test_every_graph_invoke_call_site_uses_invocation_config`;
the counter-based fan-in proof is
`tests/test_graph_compile.py::test_both_flow_preserves_reducers_and_runs_synthesis_once`.

**Concrete change made.** In `src/expense_agent_svc/state.py`, rejected
the bare `list[dict]` / `dict[str, object]` slots and added explicit
reducers: `docs: Annotated[list[dict[str, object]], operator.add]`,
`tool_results: Annotated[dict[str, object], _merge_tool_results]` (custom
merger that preserves both parallel branches — earlier writes win on
key-collision, matching LangGraph's write-semantics for idempotent
retries), `cost_usd_e5: Annotated[int, operator.add]`,
`visited_nodes: Annotated[list[str], operator.add]`,
`errors: Annotated[list[str], operator.add]`, plus `add_messages` for
`messages`. Only serialisable scalars in `AgentState`; every
non-serialisable dependency lives in `dependencies.AgentDependencies` and
the per-request `RequestContext` registry.

**Reason.** Two independent Sends in the same super-step both write to
`tool_results`. Without a reducer the later write silently clobbers the
earlier one. The mismatch surfaces as a missing branch's data on
synthesis — a *silent* data-integrity failure. The custom merger keeps
both writers visible. The reducer-annotation set is verified at test
time by inspecting `typing.get_type_hints(AgentState, include_extras=True)`.

---

## Entry 2 — Instructor `FinalAnswer` and refusal path

**Batch.** Phases 6–11 (2026-07-22) — initial FinalAnswer surface; Phase
14 (2026-07-22) — wiring; Phase 15 (2026-07-22) — Instructor
`create_with_completion` usage capture.

**Prompt (user, verbatim excerpts).**
> **Phase 10 — Instructor-typed synthesis.** […] Instructor usage/cost
> capture […] Requirements: parsed FinalAnswer for state output;
> raw_completion.usage for integer cost accounting; […] preserve
> `response_model=FinalAnswer`; preserve `max_retries=2`; preserve
> deterministic empty-context refusal with no model call; do not expose
> raw_completion in AgentState; no cost estimation when usage absent

**Raw response excerpt (paraphrased).**
> The AI SDK's ["free-text answer + regex citations"] path is
> foot-guns central — Instructor's `response_model=FinalAnswer` gives
> the same shape at compile time and rejects malformed model output at
> parse time. I'm defining `Citation` (doc_id + quote 10..240 chars,
> `extra="forbid"`) and `FinalAnswer` (text 1..2000, list[Citation],
> confidence in [0, 1], `extra="forbid"`). For empty-context refusals I
> short-circuit *before* touching the model — deterministic
> `FinalAnswer("I do not have grounded context …", citations=[],
> confidence=0.2)`. Instructor 1.15.4 exposes
> `AsyncInstructor.messages.create_with_completion` returning
> `(parsed_model, raw_completion)`. I'm using that in the production
> path so `raw_completion.usage.input_tokens/output_tokens` feed real
> integer cost into `BudgetGuard.record_usage` at the configured
> per-M rates. Missing usage counts as zero — I never fabricate
> tokens. The fake-friendly `messages.create` path stays for tests
> that don't need usage capture.

**Verdict.** **Used as is with two follow-up refinements.**
- Initial refusal `confidence=0.2` (below the 0.4 floor the spec names).
- `_bind_default_synthesizer` auto-detects whether the injected client
  exposes `create_with_completion` — only then does it wire the
  production synthesizer; test fakes with just `create` still work.

**Concrete change made.** `nodes/synthesis.py::_synthesis_body` guards
the empty-context branch first, then invokes `create_with_completion`
via an injectable `UsageAwareSynthesizer`. `raw_completion` never
enters `AgentState` — only `FinalAnswer.model_dump(mode="json")` does
(proven by `test_no_pydantic_leak_in_state`). `max_retries=2` is
preserved as an explicit kwarg on the model call and asserted in
`tests/test_synthesis_node.py::test_nonempty_context_invokes_instructor_with_correct_kwargs`.

**Reason.** A free-text answer path forces the frontend to re-parse
citations from unstructured text, which is exactly where the "the model
invented a doc_id" failure mode lives. `extra="forbid"` on Citation and
FinalAnswer makes a hallucinated field a hard validation error, not a
silent typo. The deterministic refusal keeps the empty-context path
zero-cost and reproducible — the same fixture answer every time.

---

## Entry 3 — Trajectory, RAGAS, and cost gate

**Batch.** Phases 16–18 (2026-07-23).

**Prompt (user, verbatim excerpts).**
> **PHASE 18 — 20-row trajectory and eval gate** […] There must be
> exactly 20 committed scenario rows. […] Parallel worker order is
> nondeterministic. Implement ordered semantics: docs-only: retrieval
> before synthesis; API-only: api before synthesis; both: retrieval and
> api may appear in either order but both must appear before exactly
> one synthesis; unrelated additional nodes are a mismatch unless
> explicitly allowed. Do not use simple set inclusion. […] External
> RAGAS evaluation […] do not report deterministic fixture values as
> measured RAGAS scores […] baseline must clearly say
> `source: deterministic_fixture` […] exactly 15.00% passes; more than
> 15.00% fails; baseline zero handled safely; never overwrite the
> committed baseline during a failing gate.

**Raw response excerpt (paraphrased).**
> Set-based matching is exactly what the assignment rules out — a
> "synthesis first, then a worker" sequence would score 1.0 with a set
> check, which is wrong. I'm implementing `evals/trajectory.py::
> trajectory_match(actual, expected)` with strict ordering: `set(actual)
> == set(expected)`, `count(synthesis_agent) == 1`, synthesis is last,
> and every non-synthesis worker in `expected` must appear at some index
> *before* the terminal synthesis. The both-branch allows retrieval and
> api in either order because LangGraph's parallel dispatch does not
> guarantee visit order. For the CI gate I'm building 20 committed rows
> covering docs-only, API-only, both, unknown-default (defaults to
> retrieval), plus explicit refusal rows — a mix across
> tenant-{a,b,c}. External RAGAS is a *separate* code path
> (`--gate --external`); the deterministic gate never depends on it.
> The baseline lives at `evals/last_run.json` labelled
> `"source": "deterministic_fixture"` with `"faithfulness": null` — I
> refuse to write a measured-shaped score into a deterministic fixture.

**Verdict.** **Used as is** — all 8 required trajectory-matcher tests
pass; the "exactly 20 committed rows" invariant is enforced by
`load_scenarios` at test time. Cost regression is `(current - baseline)
/ baseline`; `<= 0.15` passes so 15.00 % exactly is green, and a
zero-baseline path returns True when `current <= 0` and False otherwise.

**Concrete change made.**
- `evals/scenarios.jsonl` — exactly 20 rows across policy-*, order-*,
  refund-*, combo-*, eligibility-*, unknown-*, refusal-* categories,
  distributed across tenant-a/b/c.
- `evals/trajectory.py::trajectory_match` — ordered subsequence with
  the parallel-worker exception explicitly encoded.
- `src/expense_agent_svc/scripts/eval.py::run_deterministic` +
  `check_cost_regression` + `run_external`. External path skips
  refusal/unknown rows (17 grounded scenarios contribute).
- `evals/last_run.json` — committed baseline, `"faithfulness": null`,
  never overwritten by `--gate` (`test_ordinary_gate_never_writes_to_committed_baseline`
  asserts the bytes are unchanged before/after a gate run).
- Local skip (`EXPENSE_AGENT_ALLOW_EXTERNAL_EVAL_SKIP=1`) reports
  `status="skipped", faithfulness=null` — never a fabricated number.
  CI never exports the skip flag (proven by the workflow test).

**Reason.** Set-inclusion trajectory matching would pass "supervisor
executed nothing then synthesis produced garbage" as long as the
symbols appeared somewhere. Ordering catches real supervisor breakage.
The `source: deterministic_fixture` label is the difference between "we
tested our local ceiling holds" and "we measured production
faithfulness"; conflating those is exactly the anti-pattern the rubric
calls out. The production sampler in `sampling.py` is deliberately
non-blocking and owned by an `asyncio.Task` set drained by `aclose()` —
it never gates a user request and is not the CI gate.

---

## Entry 4 — W7D4 UUID v5 compatibility

**Batch.** Phases 6–11 (2026-07-22).

**Prompt (user, verbatim excerpts).**
> **DECISION — UUID5 COMPATIBILITY.** The installed W7D4
> `CreateRefundArgs` currently accepts only UUID version 4. W7D5
> explicitly requires deterministic UUID5 idempotency keys. Implement
> the backward-compatible solution: 1. Update the W7D4 MCP schema
> validator to accept UUID versions 4 and 5. 2. Preserve UUID4 behavior
> and tests. […] This compatibility change must be its own commit.

**Raw response excerpt (paraphrased).**
> Two options: (a) relax the W7D4 schema, or (b) generate v4-shaped
> deterministic UUIDs by seeding a `hashlib` byte string. Option (a)
> keeps the standard UUID surface intact — v4 is still random for
> interactive callers; v5 is deterministic for the W7D5 agent. Option
> (b) would hide the determinism in a bespoke UUID version marker,
> which downstream tooling parsing `.version` would misread. Going
> with (a): the field validator now accepts v4 OR v5 and continues to
> reject v1/v2/v3. Committed separately as
> `feat(mcp): accept deterministic UUID5 idempotency keys`.

**Verdict.** **Used as is** — five new schema tests in
`expense-mcp-server/tests/test_schemas.py` enforce the accept/reject
policy (v4 ok, v5 ok, v1 rejected, v3 rejected, malformed rejected).
W7D4 baseline stays 82 passed / 1 honest Docker E2E skip.

---

## Entry 5 — SSE / AI SDK v4 wire protocol

**Batch.** Phases 15 (2026-07-22) and 16 (2026-07-23).

**Prompt (user, verbatim excerpts).**
> Protocol frames: `0:<json-encoded string>\n` […] `2:<json-encoded
> object>\n` […] `3:<json-encoded object>\n`. Use JSON encoding, not
> manual quote escaping. […] Never expose exception repr, DSN, JWT,
> API key, tool arguments containing sensitive text, internal
> hostnames, stack traces.

**Raw response excerpt (paraphrased).**
> Initial implementation shipped channel-2 as a raw object and
> channel-3 as `{"error": code, "message": ...}`. Frontend tests
> against `@ai-sdk/react@1.2.0` immediately failed on the channel-2
> path — reading the installed `@ai-sdk/ui-utils` grammar showed that
> channel-2 expects a JSON *array* (parsed into `useChat.data:
> JSONValue[]`) and channel-3 expects a JSON *string* (thrown through
> `useChat.error`). Changing the backend wire to `2:[{payload}]` and
> `3:"code_slug"` fixed the frontend without weakening the
> assignment's `0:/2:/3:` channel semantics.

**Verdict.** **Modified** — backend `_final_frame` now wraps in a
one-element array; `_error_frame` now emits just the code string. The
safe human message is looked up in the client's
`SAFE_ERROR_MESSAGES` catalogue, so no exception repr / DSN / token
appears on the wire. Nineteen SSE tests were updated to match.

---

## Entry 6 — `AsyncPostgresSaver` lifecycle

**Batch.** Phase 12 (2026-07-22) and Phase 14 (2026-07-22).

**Prompt (user, verbatim excerpts).**
> Installed contract already discovered: `AsyncPostgresSaver.
> from_conn_string(...)` returns an async context manager; its
> connection remains valid only while that context manager is open;
> `setup` is asynchronous; graph compilation must occur while the
> saver context is alive. Do not call `.__enter__()` / `.__aenter__()`
> manually without matching cleanup.

**Raw response excerpt (paraphrased).**
> The lesson snippets store `saver = AsyncPostgresSaver.from_conn_string(dsn)`
> and use it later — that leaves the connection unowned. Installed
> langgraph-checkpoint-postgres 3.1.0's `from_conn_string` is an
> `@asynccontextmanager`, so I'm entering it inside the FastAPI
> lifespan's `contextlib.AsyncExitStack`. The compiled graph receives
> the live saver as a parameter; nothing holds a reference outside the
> `async with`. Restart-resume is a *deterministic* simulation: exit
> the first saver's async context fully, open a new saver on the same
> DSN, call `setup()` again (idempotent), read back the thread's state
> via `graph.aget_state(config)` and assert the prior docs /
> tool_results / answer survived. That is not a real pod kill — it is
> a controlled context-manager exit — and I document that as such.

**Verdict.** **Used as is** — four live-Postgres integration tests
pass against the local `w7d5-postgres` container.

---

## Entry 7 — Deployment honesty (Argo, ECR, CloudFormation)

**Batch.** Phases 19–20 (2026-07-23).

**Prompt (user, verbatim excerpts).**
> Do not: […] deploy CloudFormation, create the ECR repository, log
> into Argo CD, apply the Argo Application, modify or commit the
> local config repository, claim Argo Synced/Healthy, claim
> CloudFormation CREATE_COMPLETE, claim an image was pushed, claim
> config-repo reconciliation occurred, fabricate AWS roles,
> config-repo URLs, paths, secrets, action SHAs, or run URLs.

**Raw response excerpt (paraphrased).**
> The GitOps Argo Application points at
> `https://github.com/AI-Native-2026-06-01-Intuit/pranav-kuchibhotla-expense-config.git`
> (the actual remote observed on disk) at path
> `expense-agent-svc/overlays/prod` — a path that does not yet exist in
> the config repo. I'm annotating the Application manifest with a
> comment naming that gap explicitly, and providing
> `scripts/bump_config_image.py --allow-bootstrap
> --bootstrap-template …/expense-agent-svc/gitops/overlays/prod` for
> the merge workflow to seed it. The CI merge-to-main job requires
> two repo variables — `EXPENSE_AGENT_AWS_VALIDATION_ROLE_ARN` and
> `EXPENSE_AGENT_DEPLOY_ROLE_ARN` — with preflight steps that fail
> loudly if empty. `ecr_preflight.sh` fails with the exact operator-
> actionable message the spec dictates; it never runs `aws ecr
> create-repository`. Every `uses:` line is pinned to a full 40-hex
> SHA reused from the repo's approved pins. Rollback rehearsal is
> `PENDING` — the runbook records that explicitly and lists the six
> blockers before it can move to a real timestamped record.

**Verdict.** **Used as is** — no AWS deployment, no ECR creation, no
Argo login, no `argocd apply`, no image push occurred in this session.
The local config repo (`git -C ~/Documents/pranav-kuchibhotla-expense-config
status --porcelain`) is empty; branch stayed on `w6d5-implementation`.

---

## What was rejected (not merged)

- **Bare state slots.** `docs: list[dict]` without a reducer was drafted
  first; rejected once the both-branch counter test showed the parallel
  writes were silently overwritten.
- **Free-text synthesis + regex citation extraction.** Rejected in
  favour of Instructor `FinalAnswer` with `extra="forbid"`. See
  Entry 2.
- **Set-based trajectory matching.** Rejected because "synthesis first,
  then a random worker" would score 1.0. See Entry 3.
- **Placeholder AWS account `123456789012`.** Never landed in any
  production file; asserted absent by three separate tests.
- **`MemorySaver` in production source.** Used only in unit tests where
  a real checkpointer is not required; guardrail
  `test_no_memorysaver_in_production_source` walks `src/` and fails on
  any hit.
- **`os.kill` / `subprocess.Popen` for the checkpoint-resume test.**
  Rejected in favour of a controlled `async with` context exit —
  documented in the resume test as a "deterministic restart simulation"
  rather than a real pod kill.
- **Invented RAGAS scores.** `evals/last_run.json` has
  `"faithfulness": null` and `"external_metric_status":
  "not_measured"`. Local skip reports `status="skipped"` with
  `faithfulness=null`. CI never exports the skip flag.
- **Claiming Argo Synced / CloudFormation CREATE_COMPLETE / ECR push.**
  Every one of these operations is marked PENDING in the runbook and
  the evidence doc; the rollback rehearsal is explicitly
  "Pending real Argo CD login and production deployment."
