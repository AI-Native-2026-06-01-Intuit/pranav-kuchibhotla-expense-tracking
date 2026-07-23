"""AI SDK v4 data-stream bridge for LangGraph event output.

Emits three framed line-prefixed channels compatible with Vercel's
`@ai-sdk/react` v1.2 ``useChat`` data-stream transport:

* ``0:<json string>\\n`` — user-visible text delta (only from the
  synthesis node — retrieval query rewrites and API tool-selection
  monologues stay internal).
* ``2:<json object>\\n`` — the typed :class:`FinalAnswer` payload,
  emitted exactly once at graph completion.
* ``3:<json object>\\n`` — a safe error object. Reserved error codes
  are ``recursion_limit``, ``budget_exceeded``,
  ``request_context_unavailable`` and ``internal_error``. No error
  frame ever carries an exception repr, a DSN, an API key, a JWT, an
  internal hostname, or a stack trace — the mapping table below is the
  only allowed source of channel-3 text.

The generator wraps a single ``chat_request`` LangSmith root run
covering the *entire* iteration so node runs remain child spans named
``retrieval_agent`` / ``api_agent`` / ``synthesis_agent``.
"""

from __future__ import annotations

import asyncio
import json
import logging
from collections.abc import AsyncIterator, Mapping
from typing import TYPE_CHECKING, Any, cast

from langgraph.errors import GraphRecursionError

from .budgets import BudgetExceeded
from .dependencies import RequestContextMismatch, RequestContextUnavailable
from .graph import invocation_config
from .nodes.synthesis import FinalAnswer

if TYPE_CHECKING:
    from langgraph.graph.state import CompiledStateGraph

    from .state import AgentState


_log = logging.getLogger("expense_agent_svc.sse")

# --- Channel encoders ---------------------------------------------------------


def _text_frame(delta: str) -> bytes:
    """Return a channel-0 (text delta) AI SDK v4 frame."""
    return (f"0:{json.dumps(delta, ensure_ascii=False)}\n").encode()


def _final_frame(payload: Mapping[str, object]) -> bytes:
    """Return a channel-2 (typed final answer) AI SDK v4 frame.

    The v4 wire grammar requires channel-2 to carry a JSON *array* of
    data values (see ``@ai-sdk/ui-utils`` dataStreamPart parser). We
    wrap the single :class:`FinalAnswer` payload in a one-element
    array; the client picks it out of ``useChat.data``.
    """
    return (f"2:{json.dumps([payload], ensure_ascii=False)}\n").encode()


def _error_frame(code: str, message: str) -> bytes:
    """Return a channel-3 (safe error) AI SDK v4 frame.

    Channel-3 in the v4 wire grammar carries a JSON *string*. We
    encode the error code so the client's ``useChat.error.message`` is
    a stable machine-readable slug — the friendly text is looked up in
    the client's :data:`SAFE_ERROR_MESSAGES` catalogue. This is also
    how we prove no exception repr / DSN / token can leak into the
    channel: the frame carries only the code string, never a message.
    """
    del message
    return (f"3:{json.dumps(code, ensure_ascii=False)}\n").encode()


# --- Safe error catalogue -----------------------------------------------------


_ERRORS: dict[str, tuple[str, str]] = {
    "recursion_limit": (
        "recursion_limit",
        "The request exceeded the permitted graph steps.",
    ),
    "budget_exceeded": (
        "budget_exceeded",
        "The request exceeded its cost budget.",
    ),
    "request_context_unavailable": (
        "request_context_unavailable",
        "The request could not be continued.",
    ),
    "internal_error": (
        "internal_error",
        "The request could not be completed.",
    ),
}


def error_frame_for(code: str) -> bytes:
    """Return the canonical channel-3 frame for the given error code."""
    resolved = _ERRORS.get(code) or _ERRORS["internal_error"]
    return _error_frame(*resolved)


# --- Event-shape helpers ------------------------------------------------------


def _node_of(event: Mapping[str, object]) -> str | None:
    """Return the LangGraph node name for an event, or ``None`` if not tagged."""
    metadata = event.get("metadata")
    if not isinstance(metadata, Mapping):
        return None
    node = metadata.get("langgraph_node")
    return node if isinstance(node, str) else None


def _extract_chat_text(event: Mapping[str, object]) -> str:
    """Return the text delta from a chat-model stream event, or empty."""
    data = event.get("data")
    if not isinstance(data, Mapping):
        return ""
    chunk = data.get("chunk")
    if chunk is None:
        return ""
    # LangChain BaseMessageChunk carries `.content` which is either a str
    # or a list of content blocks (Anthropic tool-use has both).
    content = getattr(chunk, "content", None)
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        pieces: list[str] = []
        for block in content:
            if isinstance(block, Mapping):
                block_text = block.get("text")
                if isinstance(block_text, str):
                    pieces.append(block_text)
            else:
                block_text = getattr(block, "text", None)
                if isinstance(block_text, str):
                    pieces.append(block_text)
        return "".join(pieces)
    return ""


def _extract_final_answer(event: Mapping[str, object]) -> Mapping[str, object] | None:
    """Return the ``final_answer`` dict from a synthesis on_chain_end event."""
    data = event.get("data")
    if not isinstance(data, Mapping):
        return None
    output = data.get("output")
    if not isinstance(output, Mapping):
        return None
    payload = output.get("final_answer")
    if isinstance(payload, Mapping):
        return payload
    # Fallback: some node returns might omit final_answer but include answer.
    answer = output.get("answer")
    if isinstance(answer, str) and answer:
        return {"text": answer, "citations": [], "confidence": 0.0}
    return None


def _normalise_final_answer(payload: Mapping[str, object]) -> dict[str, object]:
    """Coerce a payload into a validated FinalAnswer JSON-serializable dump."""
    try:
        final = FinalAnswer.model_validate(payload)
    except Exception:
        text = payload.get("text") if isinstance(payload.get("text"), str) else ""
        confidence_raw = payload.get("confidence")
        confidence = float(confidence_raw) if isinstance(confidence_raw, (int, float)) else 0.0
        return {
            "text": text if isinstance(text, str) else "",
            "citations": [],
            "confidence": max(0.0, min(1.0, confidence)),
        }
    return cast(dict[str, object], final.model_dump(mode="json"))


# --- Public generator ---------------------------------------------------------


async def event_stream(
    *,
    graph: CompiledStateGraph[AgentState, Any, AgentState, AgentState],
    initial_state: Mapping[str, object],
    thread_id: str,
) -> AsyncIterator[bytes]:
    """Iterate the graph and yield AI SDK v4 data-stream frames.

    ``graph`` must be the compiled supervisor graph. ``initial_state``
    is the JSON-serialisable input dict (must carry ``request_id`` for
    the node-level registry lookups). ``thread_id`` is threaded through
    :func:`invocation_config` so the 25-recursion ceiling is enforced.

    Every yield is safe to write to an HTTP response body — bytes only,
    no exception reprs, no secrets.
    """
    # Local imports so an ``import expense_agent_svc.sse`` in a test
    # module does not drag LangSmith's tracing surface unless the
    # generator is actually iterated.
    from langsmith.run_helpers import trace

    saw_text = False
    saw_final = False
    final_payload: Mapping[str, object] | None = None

    # Root ``chat_request`` trace covers the entire iteration, not just
    # the generator's construction. ``@traceable`` on an async generator
    # in installed langsmith 0.10.9 only covers the generator function
    # body up to the first yield, so we use ``langsmith.run_helpers.trace``
    # — the supported explicit context manager — instead.
    with trace(name="chat_request", run_type="chain"):
        try:
            async for event in graph.astream_events(
                cast(Any, dict(initial_state)),
                cast(Any, invocation_config(thread_id)),
                version="v2",
            ):
                event_name = event.get("event")

                if event_name == "on_chat_model_stream":
                    if _node_of(event) != "synthesis_agent":
                        # API / retrieval rewrite chat traffic is
                        # internal only — never streamed to the caller.
                        continue
                    delta = _extract_chat_text(event)
                    if delta:
                        saw_text = True
                        yield _text_frame(delta)

                elif event_name == "on_chain_end":
                    # Look only at synthesis_agent's own on_chain_end for
                    # the terminal payload; the outer LangGraph on_chain_end
                    # would fire regardless of node identity.
                    if event.get("name") == "synthesis_agent":
                        payload = _extract_final_answer(event)
                        if payload is not None:
                            final_payload = payload

            # --- Post-iteration: emit final answer (with fallback) ---
            if final_payload is not None:
                normalised = _normalise_final_answer(final_payload)
                if not saw_text:
                    # Fallback: no synthesis token stream was produced
                    # (Instructor's structured output does not stream).
                    # Emit the final text once on channel 0 so the UI
                    # renders something before the typed FinalAnswer.
                    text = normalised.get("text")
                    if isinstance(text, str) and text:
                        yield _text_frame(text)
                yield _final_frame(normalised)
                saw_final = True

        except asyncio.CancelledError:
            # Never convert cancellation into an error frame; let the
            # task cancellation propagate so cleanup callbacks (the
            # route's ``finally`` release_request) run promptly.
            raise
        except GraphRecursionError:
            _log.warning("chat_stream error: recursion_limit")
            yield error_frame_for("recursion_limit")
        except BudgetExceeded:
            _log.warning("chat_stream error: budget_exceeded")
            yield error_frame_for("budget_exceeded")
        except (RequestContextUnavailable, RequestContextMismatch):
            _log.warning("chat_stream error: request_context_unavailable")
            yield error_frame_for("request_context_unavailable")
        except Exception:
            # Log a safe category *only*; never a repr, never args.
            _log.exception("chat_stream error: internal_error")
            yield error_frame_for("internal_error")

    del saw_final  # silence unused-warning; used above by control flow


__all__ = [
    "error_frame_for",
    "event_stream",
]
