# expense-mcp-server (W7D4)

FastMCP server publishing UptimeCrew expense Spring endpoints and the
W7D3 expense-ai RAG pipeline behind a single MCP surface with two
transports (stdio for Claude Desktop, SSE/HTTP for W7D5).

## Tools

| Tool                          | What it does                                       |
| ----------------------------- | -------------------------------------------------- |
| `orders.get_order`            | Read a tenant-scoped synthetic order.              |
| `orders.create_refund`        | Idempotent refund write with a required UUID v4 or v5. |
| `llm.chat`                    | Proxied bounded LLM chat.                          |
| `rag.retrieve_and_generate`   | In-process W7D3 hybrid+MMR+rerank pipeline.        |

## Resource

`expense://catalogue` — read-only server/tool catalogue.

## Transports

- `expense-mcp-server` — stdio JSON-RPC for Claude Desktop.
- `expense-mcp-server-sse` — HTTP/SSE for W7D5 hand-off.

## Quickstart

```
uv sync --frozen
uv run pytest -v
uv run expense-mcp-server-sse --help
```

See `docs/evidence/w7d4-static-validation.md` for the recorded gate run
and `../expense-ai/PYTHON.md` for the W7D4 architecture section.

## W7D5 compatibility note — UUID v4 or v5 for `idempotency_key`

`orders.create_refund` accepts either UUID v4 or UUID v5 on its
`idempotency_key` field. UUID v4 remains the interactive default for
callers that mint a fresh random key per attempt; UUID v5 is added so
the W7D5 `expense-agent-svc` LangGraph service can derive a
deterministic key from `(thread_id | tool_name | canonical args hash)`
and have a checkpoint replay produce the same key — the upstream
ledger then deduplicates the retry instead of double-refunding. Other
UUID versions (v1/v2/v3) remain rejected because v1 leaks the host MAC
and v3 is the MD5 twin of v5 with no additional value here.

