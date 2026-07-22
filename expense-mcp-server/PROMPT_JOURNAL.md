# expense-mcp-server prompt journal (W7D4)

W7D4 was driven by a single combined Claude Code session working
against the whole codebase. This journal captures three
representative prompt-response pairs — one per major design axis — and
notes for each whether the model output was used as-is, modified, or
rejected. The single-prompt origin is deliberate: it kept the model
inside one context window across Spring + Python + CI so cross-file
consistency (JWT scope names, DTO shapes, error codes) did not drift.

---

## Entry 1 — orders.create_refund description + schema

**Prompt (abridged)**

> Draft the FastMCP tool description and Pydantic v2 args model for
> `orders.create_refund`. It must accept `order_id`, `amount` as
> Decimal, `reason` (4..200 chars), `tenant_id`, and a UUID v4
> `idempotency_key`. Description must contain the phrases "Use this"
> and "Do NOT" (case-sensitive), be ≥200 chars, and end with a
> concrete example.

**Response excerpt**

> ```python
> class CreateRefundArgs(_Strict):
>     order_id: Annotated[str, Field(min_length=1, max_length=128)]
>     amount: Decimal
>     reason: Annotated[str, Field(min_length=4, max_length=200)]
>     tenant_id: TenantId
>     idempotency_key: UUID
> ```
> plus a description string that ended with "…Example: orders.create_refund(order_id=…, idempotency_key='<uuid4>') returns a RefundView."

**Verdict — Modified.** The first draft accepted any UUID version.
The user rubric requires UUID v4 specifically, so a
`@field_validator("idempotency_key")` was added that raises when
`v.version != 4`. The description was tightened so the "Do NOT" clause
called out the specific misuse ("reuse a key across
logically-different refunds") rather than a generic warning. The
`Annotated[Decimal, …]` variant the model first suggested was
dropped in favour of a custom validator that both rejects negative
amounts and rejects more than two decimal places at parse time.

---

## Entry 2 — FastMCP lifespan + stderr-only logging

**Prompt (abridged)**

> Wire a FastMCP lifespan that opens one shared `httpx.AsyncClient`
> per upstream (orders + llm-proxy), configures structlog to write JSON
> to `sys.stderr` (never stdout), and closes both clients on shutdown.
> Tools must reach the clients via the FastMCP `Context` object, not
> module globals.

**Response excerpt**

> A first draft that used `structlog.PrintLoggerFactory()` without a
> `file=` argument, and a lifespan that put the `httpx.AsyncClient` on
> a module-level variable "so tools can import it directly."

**Verdict — Rejected, then rewritten.** Both defaults were wrong:
`PrintLoggerFactory()` without `file=sys.stderr` writes to stdout,
which would corrupt stdio JSON-RPC framing; and putting the client on
a module global would break the "close on shutdown" invariant and make
tests hard to isolate. The final `app.py::lifespan` yields a frozen
`Deps` dataclass wrapping the two clients, the settings, and a
`rag_call` factory; tools resolve it via `ctx.request_context.lifespan_context`
through a small `deps_from(ctx)` helper. `telemetry.py::configure_logging`
explicitly passes `file=sys.stderr` and clears the root logger's
existing handlers so no library can sneak a stdout handler in.

---

## Entry 3 — Testcontainers E2E idempotency assertion

**Prompt (abridged)**

> Write the Testcontainers E2E that spawns the `expense-mcp-server`
> stdio subprocess against a live `expense-api` Docker image, calls
> `orders.create_refund` twice with the same UUID v4, and asserts the
> same `refund_id` on both responses. It must skip cleanly when the
> Docker image is unavailable, never fabricate a pass.

**Response excerpt**

> A first draft that hard-coded `image = "expense-orders:w3d1"` and
> assumed a matching Compose service existed.

**Verdict — Modified.** The rubric explicitly warned that the
appendix's image name may not exist in this repo — and it did not; the
repo ships `expense-api`, not `expense-orders`, and no `w3d1` tag
existed. The final test reads `EXPENSE_MCP_E2E_IMAGE` from the
environment, `pytest.skip`s with a precise reason if either Docker or
the image is missing, and the merge-to-main CI job builds
`expense-api:e2e` from the repo's real Dockerfile before running.
The idempotency assertion compares the two `CallToolResult.content`
payloads directly rather than parsing out `refund_id`, so a serialization
regression on the Spring side also trips the assertion instead of silently
comparing to `None`. The synthetic order row (`ord-synth-9001`,
`tenant-a`) is seeded in `V5__orders_refunds.sql`, so the E2E does not
need a separate fixture-load step.
