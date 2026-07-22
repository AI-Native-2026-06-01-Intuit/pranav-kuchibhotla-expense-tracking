"""Read-only ``expense://catalogue`` resource.

Returns a structured snapshot the client can use for routing without
issuing tool calls: server identity, the four tool names + their
purposes, corpus stats read from the committed synthetic fixtures,
and the tenants this server accepts.
"""

from __future__ import annotations

import json
from pathlib import Path

from .. import __version__
from ..app import mcp
from .schemas import ALLOWED_TENANTS

# Fixture directory is committed alongside the package so this stays
# deterministic even when the runtime deps container has no network.
_FIXTURE_DIR = Path(__file__).resolve().parents[3] / "tests" / "fixtures"


def _corpus_stats() -> dict[str, int]:
    """Report doc/chunk counts from committed fixture files, if present."""
    stats = {"docs": 0, "chunks": 0}
    if not _FIXTURE_DIR.is_dir():
        return stats
    for path in _FIXTURE_DIR.glob("rag_*.json"):
        try:
            payload = json.loads(path.read_text())
        except (OSError, json.JSONDecodeError):
            continue
        answer = payload.get("expected_answer", {})
        citations = answer.get("citations") or []
        # A fixture line contributes one "doc" per unique doc_id it
        # references and one "chunk" per citation entry.
        stats["chunks"] += len(citations)
        stats["docs"] += len({c.get("doc_id") for c in citations if isinstance(c, dict)})
    return stats


CATALOGUE_DOC = {
    "server": {"name": "expense-mcp-server", "version": __version__},
    "tools": [
        {
            "name": "orders.get_order",
            "description": "Fetch a tenant-scoped synthetic order by id.",
        },
        {
            "name": "orders.create_refund",
            "description": (
                "Create an idempotent refund; same (order_id, "
                "idempotency_key) returns the same refund_id."
            ),
        },
        {
            "name": "llm.chat",
            "description": "Bounded, tenant-scoped chat via the Spring LLM proxy.",
        },
        {
            "name": "rag.retrieve_and_generate",
            "description": (
                "Corpus-grounded answer using the W7D3 hybrid + MMR + "
                "rerank pipeline with citations."
            ),
        },
    ],
    "supported_tenants": list(ALLOWED_TENANTS),
    "corpus_stats": _corpus_stats(),
}


@mcp.resource(
    uri="expense://catalogue",
    name="expense-catalogue",
    description="Read-only catalogue of tools, tenants, and corpus stats.",
    mime_type="application/json",
)
def catalogue() -> str:
    """Return the catalogue as a JSON string."""
    return json.dumps(CATALOGUE_DOC, sort_keys=True)


__all__ = ["CATALOGUE_DOC", "catalogue"]
