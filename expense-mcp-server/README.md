# expense-mcp-server (W7D4)

FastMCP server publishing UptimeCrew expense Spring endpoints and the
W7D3 expense-ai RAG pipeline behind a single MCP surface with two
transports (stdio for Claude Desktop, SSE/HTTP for W7D5).

## Tools

| Tool                          | What it does                                       |
| ----------------------------- | -------------------------------------------------- |
| `orders.get_order`            | Read a tenant-scoped synthetic order.              |
| `orders.create_refund`        | Idempotent refund write with a required UUID v4.   |
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
