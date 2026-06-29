# PROMPT_JOURNAL — Week 4 Day 4

AI-assisted prompts that produced shipped code on the `week04/day4/...` branch.

## Task 1 — Vercel AI SDK + Hono /api/chat proxy + first useChat panel

**Intent:** Install `ai`, `@ai-sdk/react`, `@ai-sdk/openai-compatible`, `zod`, `hono` (with `@hono/node-server` for the Node listener) and `tsx`. Stand up a `server/index.ts` Hono app and `server/api/chat.ts` route that proxies `POST /api/chat` via `streamText`/`createOpenAICompatible` to `http://localhost:8080/ai` (model `uptime-crew-assistant`). Add a Vite dev proxy from `/api/chat` → `localhost:3001`. Create a `MerchantChatPanel` at `/merchants/:id/chat` using `useChat`.

**Output summary:** New `server/` tree with Hono app, separate `tsconfig.server.json` for Node target, Vite proxy, route added to `router.tsx`, new chat panel, link added from `MerchantSummaryPage` to the chat panel.

**Verdict:** Accepted (with one judgment call).

**Notes:**
- **Accepted** keeping the upstream baseURL server-side — browser only ever talks to `/api/chat`, never sees the upstream host. Threat-model comment landed in `chat.ts`.
- **Accepted** the SSE no-buffering headers (`Content-Type: text/event-stream`, `Cache-Control: no-cache, no-transform`, `Connection: keep-alive`, `X-Accel-Buffering: no`) — must not buffer; SSE has to stream chunk by chunk.
- **Accepted** clear separation of server state (Hono / `streamText`) from React UI state (`useChat`). Persistence comes later.
- **Modified** the spec slightly: added `@hono/node-server` because Hono itself is runtime-agnostic and needs an adapter to listen on a Node port. Confirmed with user before adding.
- **Modified** tsconfig layout: added `tsconfig.server.json` so Node-targeted server code typechecks separately from DOM-targeted browser code; wired both into `npm run typecheck` and ESLint.
- **Followed** "use npm only" — no pnpm/corepack calls.

## Task 2 — Streaming UX polish + cleaner upstream error handling

**Intent:** Pull `stop`, `reload`, `error` from `useChat`; render `role="status"` while loading; add Stop (disabled when idle) and Regenerate (disabled while loading) buttons; disable Send when input is empty; `role="alert"` for errors; auto-scroll to bottom on messages change. On the server, return clean 400 on bad body, 502 on synchronous `streamText` setup failure, and don't dress up `AbortError` as an upstream failure.

**Output summary:** `MerchantChatPanel.tsx` gained the three buttons, `role="status"`, `role="alert"`, and an `endRef` + `useEffect([messages])` auto-scroll. `chat.ts` got try/catch around JSON parsing and around `streamText` setup; aborts map to a bare 499.

**Verdict:** Accepted (one lint fix during apply).

**Notes:**
- **Accepted** the 400/502/499 split. 499 isn't in Hono's `StatusCode` union, so the abort branch returns a bare `Response(null, { status: 499 })` instead of `c.body(...)`.
- **Preserved** SSE no-buffering headers — pulled them into an `SSE_HEADERS` const so the success path can't accidentally drop them.
- **Modified** the `Regenerate` `onClick`: original `onClick={() => reload()}` tripped `no-misused-promises` because `reload` returns a Promise; wrapped it in a `void` block.
- **Skipped** any backwards-compatibility shims around `isLoading` vs `status` — `useChat@1.2` exposes `status` only, so derived `isLoading` from `status === 'submitted' || 'streaming'`.

## Task 3 — Streamed tool calls + Zustand chat persistence

**Intent:** Add `server/api/chat-tools.ts` exporting `merchantTools` (`lookupMerchant` hits `GET /api/v1/merchants/${id}`; `classifyDeduction` hits `GET /api/v1/merchants?merchantId=${id}`). Wire into `streamText` with `maxSteps: 3` and an updated system prompt. Render `ToolCallCard` per `message.toolInvocations`. Persist completed assistant messages into a Zustand store via `useChat.onFinish` — never per token.

**Output summary:** Two new files (`chat-tools.ts`, `ToolCallCard.tsx`, `useMerchantChatStore.ts`) plus updates to `chat.ts` and `MerchantChatPanel.tsx`. The store mirrors `useMerchantFilterStore` style (devtools → persist → createJSONStorage with the jsdom-safe guard).

**Verdict:** Accepted (with one explicit rejection).

**Notes:**
- **Rejected** any pattern that copies `useChat.messages` into Zustand on every messages change. That would write on every token. The contract is: `onFinish` fires once per completed assistant message, and that's the only persistence write path.
- **Rejected** writing to Zustand during render. Selector pulls the action only; the call lives inside the `onFinish` callback.
- **Accepted** per-slice selector — `useMerchantChatStore((s) => s.appendAssistantMessage)` — so the component doesn't re-render when other slices change.
- **Modified** the local `ToolInvocation` shape: the SDK's `ToolInvocation` uses `any` internally for args/result, which would leak into our UI. Re-typed locally as `ToolInvocationLike` with `unknown`. Also defensive on `toolName`/`name` and `args`/`arguments` shape variants.
- **Skipped** seeding `useChat.initialMessages` from the persisted store (spec marked optional) — Message-type compatibility risk wasn't worth it for Task 3.

## Task 4 — MSW SSE handlers + Vitest tests + this journal

**Intent:** Stand up an MSW v2 handler that emits Vercel AI SDK data-stream frames (`0:"..."` then `d:{...}`) so `useChat` can be tested end-to-end. Cover streamed-token rendering, Stop, Regenerate, error path, `ToolCallCard` states, and store behavior. Add 19+ new tests so the project clears 40 total.

**Output summary:** `src/test/sse-handlers.ts` (default handler + `makeChatHandler`/`makeChatStream` helpers + `chatCallCount` ref); `handlers.ts` spreads them in; four new test files covering panel, panel error, tool card, and store.

**Verdict:** Accepted.

**Notes:**
- **Accepted** ReadableStream emitting raw `0:"text"\n` and `d:{...}\n` frames with `X-Vercel-AI-Data-Stream: v1` — that's what `useChat`'s data-protocol parser actually consumes (not real `data:`-prefixed SSE).
- **Preserved** SSE-y headers on the test stream (`Content-Type: text/event-stream`, `Cache-Control: no-cache, no-transform`) for parity with production.
- **Accepted** counting POSTs with a closure-held `chatCallCount` ref reset in `beforeEach` — simpler than spying on MSW internals.
- **Modified** the Stop test to assert on observable state (status disappears, Stop becomes disabled) rather than trying to assert "partial text shorter than full reply." That's flaky under happy-dom microtask ordering.
- **Preserved** "use npm only" through all four tasks. No production code change for tests.

## Local run notes (W4D4)

- **Vite** runs with `npm run dev` (default port 5173).
- **Hono proxy** runs with `npm run server` (port 3001). Vite forwards `/api/chat` → `localhost:3001`.
- **Live manual chat** requires the W3D4 Spring AI backend at `http://localhost:8080/ai/chat` (the proxy posts upstream there).
- **Live merchant list** requires the GraphQL backend at `http://localhost:8080/graphql` (Apollo).
- If the W3 backend is unavailable, the app may show **"Failed to fetch"** in the browser. That is expected manually — there is no offline mock layer in dev. MSW-backed tests still cover the streaming and data-layer contracts locally (`npm test`).
- **Manual fallback for verifying the UI shell only:** sign in at `/login`, then open `/merchants/stub-id-1/chat`. The chat panel renders without a live upstream, but sending will surface a `role="alert"` error until the backend is up.
