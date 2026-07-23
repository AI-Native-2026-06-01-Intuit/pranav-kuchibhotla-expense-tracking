"""SSE / AI SDK v4 data-stream generator contract.

Cover:

* Synthesis text delta → channel 0 (valid JSON, only user-visible text).
* Retrieval / API worker chat traffic is filtered out (not streamed).
* Final answer → channel 2 exactly once.
* Fallback: when no synthesis text delta was seen, emit the final
  ``text`` once on channel 0 before channel 2.
* No duplicate text when synthesis deltas were seen.
* Recursion / budget / request-context / generic errors → safe
  channel-3 frames whose content is drawn only from the canonical map
  (no exception repr, no DSN, no secret).
* ``asyncio.CancelledError`` is not converted into a channel-3 frame.
* The generator uses :func:`invocation_config` — recursion limit 25 is
  present on the config the graph sees.
"""

from __future__ import annotations

import asyncio
import json
from collections.abc import AsyncIterator, Mapping
from typing import Any, cast

import pytest
from langgraph.errors import GraphRecursionError

from expense_agent_svc.budgets import BudgetExceeded
from expense_agent_svc.dependencies import (
    RequestContextMismatch,
    RequestContextUnavailable,
)
from expense_agent_svc.sse import error_frame_for, event_stream

# ---------- Fake graph objects ----------


class _FakeChunk:
    def __init__(self, text: str) -> None:
        self.content = text


def _stream_event(*, node: str, text: str) -> dict[str, Any]:
    return {
        "event": "on_chat_model_stream",
        "name": "ChatAnthropic",
        "metadata": {"langgraph_node": node},
        "data": {"chunk": _FakeChunk(text)},
    }


def _synth_end_event(final_answer: dict[str, object] | None) -> dict[str, Any]:
    output: dict[str, object] = {
        "answer": final_answer["text"] if final_answer else "",
        "visited_nodes": ["synthesis_agent"],
        "errors": [],
    }
    if final_answer is not None:
        output["final_answer"] = final_answer
    return {
        "event": "on_chain_end",
        "name": "synthesis_agent",
        "metadata": {"langgraph_node": "synthesis_agent"},
        "data": {"output": output},
    }


class _FakeGraph:
    """Minimal graph object exposing only what event_stream calls."""

    def __init__(
        self,
        events: list[dict[str, Any]] | None = None,
        *,
        raise_exc: BaseException | None = None,
    ) -> None:
        self._events = events or []
        self._raise_exc = raise_exc
        self.received_config: dict[str, object] | None = None
        self.received_input: dict[str, object] | None = None

    def astream_events(
        self,
        input_state: object,
        config: object,
        *,
        version: str,
    ) -> AsyncIterator[dict[str, Any]]:
        self.received_input = cast(dict[str, object], input_state)
        self.received_config = cast(dict[str, object], config)
        assert version == "v2"
        events = list(self._events)
        raise_exc = self._raise_exc

        async def gen() -> AsyncIterator[dict[str, Any]]:
            for ev in events:
                yield ev
            if raise_exc is not None:
                raise raise_exc

        return gen()


async def _drain(gen: AsyncIterator[bytes]) -> list[bytes]:
    frames: list[bytes] = []
    async for frame in gen:
        frames.append(frame)
    return frames


def _decode(frame: bytes) -> tuple[str, object]:
    line = frame.decode()
    channel, _, rest = line.partition(":")
    return channel, json.loads(rest.rstrip("\n"))


# ---------- Channel 0 / channel 2 happy paths ----------


@pytest.mark.asyncio
async def test_synthesis_text_delta_emitted_on_channel_zero() -> None:
    final = {"text": "final policy answer", "citations": [], "confidence": 0.8}
    graph = _FakeGraph(
        [
            _stream_event(node="synthesis_agent", text="Hello "),
            _stream_event(node="synthesis_agent", text="world"),
            _synth_end_event(final),
        ]
    )
    frames = await _drain(
        event_stream(
            graph=cast(Any, graph),
            initial_state={"question": "q", "tenant_id": "tenant-a", "request_id": "r"},
            thread_id="thread-1",
        )
    )
    decoded = [_decode(f) for f in frames]
    channels = [c for c, _ in decoded]
    # First text delta, then second, then channel 2.
    assert channels == ["0", "0", "2"]
    assert decoded[0][1] == "Hello "
    assert decoded[1][1] == "world"
    # AI SDK v4 channel-2 carries a JSON array; unwrap the single
    # FinalAnswer element.
    payload_list = decoded[2][1]
    assert isinstance(payload_list, list) and len(payload_list) == 1
    payload = payload_list[0]
    assert isinstance(payload, dict)
    assert payload["text"] == "final policy answer"
    assert payload["citations"] == []


@pytest.mark.asyncio
async def test_non_synthesis_chat_stream_is_filtered_out() -> None:
    # A retrieval-agent query-rewrite chat stream must not leak to
    # channel 0 — only synthesis text is user-visible.
    final = {"text": "answer", "citations": [], "confidence": 0.5}
    graph = _FakeGraph(
        [
            _stream_event(node="retrieval_agent", text="rewrite text"),
            _stream_event(node="api_agent", text="tool selection text"),
            _synth_end_event(final),
        ]
    )
    frames = await _drain(
        event_stream(
            graph=cast(Any, graph),
            initial_state={"question": "q", "tenant_id": "tenant-a", "request_id": "r"},
            thread_id="thread-1",
        )
    )
    decoded = [_decode(f) for f in frames]
    channels = [c for c, _ in decoded]
    # Fallback text (the final text) once on channel 0, then channel 2.
    assert channels == ["0", "2"]
    assert decoded[0][1] == "answer"


@pytest.mark.asyncio
async def test_final_answer_emitted_exactly_once() -> None:
    final = {"text": "one", "citations": [], "confidence": 0.5}
    graph = _FakeGraph(
        [
            _stream_event(node="synthesis_agent", text="one"),
            _synth_end_event(final),
        ]
    )
    frames = await _drain(
        event_stream(
            graph=cast(Any, graph),
            initial_state={"question": "q", "tenant_id": "tenant-a", "request_id": "r"},
            thread_id="thread-1",
        )
    )
    channels = [_decode(f)[0] for f in frames]
    assert channels.count("2") == 1


@pytest.mark.asyncio
async def test_no_duplicate_text_when_deltas_present() -> None:
    """Deltas already covered the text — the fallback text must NOT fire."""
    final = {"text": "combined delta text", "citations": [], "confidence": 0.9}
    graph = _FakeGraph(
        [
            _stream_event(node="synthesis_agent", text="combined delta text"),
            _synth_end_event(final),
        ]
    )
    frames = await _drain(
        event_stream(
            graph=cast(Any, graph),
            initial_state={"question": "q", "tenant_id": "tenant-a", "request_id": "r"},
            thread_id="thread-1",
        )
    )
    text_frames = [f for f in frames if f.startswith(b"0:")]
    assert len(text_frames) == 1


# ---------- Channel 3 error mappings ----------


@pytest.mark.asyncio
async def test_graph_recursion_error_maps_to_recursion_limit_frame() -> None:
    graph = _FakeGraph(raise_exc=GraphRecursionError())
    frames = await _drain(
        event_stream(
            graph=cast(Any, graph),
            initial_state={"question": "q", "tenant_id": "tenant-a", "request_id": "r"},
            thread_id="thread-1",
        )
    )
    assert frames == [error_frame_for("recursion_limit")]
    channel, payload = _decode(frames[0])
    assert channel == "3"
    # AI SDK v4 channel-3 carries a JSON string; the client resolves
    # the safe human message from the shared code catalogue.
    assert payload == "recursion_limit"


@pytest.mark.asyncio
async def test_budget_exceeded_maps_to_budget_frame() -> None:
    graph = _FakeGraph(raise_exc=BudgetExceeded("boom"))
    frames = await _drain(
        event_stream(
            graph=cast(Any, graph),
            initial_state={"question": "q", "tenant_id": "tenant-a", "request_id": "r"},
            thread_id="thread-1",
        )
    )
    channel, payload = _decode(frames[0])
    assert channel == "3"
    assert payload == "budget_exceeded"
    # The raw exception string ("boom") must not appear in the frame.
    assert b"boom" not in frames[0]


@pytest.mark.asyncio
async def test_request_context_unavailable_maps_to_safe_frame() -> None:
    graph = _FakeGraph(raise_exc=RequestContextUnavailable("state carries no request_id"))
    frames = await _drain(
        event_stream(
            graph=cast(Any, graph),
            initial_state={"question": "q", "tenant_id": "tenant-a", "request_id": "r"},
            thread_id="thread-1",
        )
    )
    channel, payload = _decode(frames[0])
    assert channel == "3"
    assert payload == "request_context_unavailable"


@pytest.mark.asyncio
async def test_context_mismatch_maps_to_safe_frame() -> None:
    graph = _FakeGraph(raise_exc=RequestContextMismatch("tenant mismatch"))
    frames = await _drain(
        event_stream(
            graph=cast(Any, graph),
            initial_state={"question": "q", "tenant_id": "tenant-a", "request_id": "r"},
            thread_id="thread-1",
        )
    )
    channel, payload = _decode(frames[0])
    assert channel == "3"
    assert payload == "request_context_unavailable"


@pytest.mark.asyncio
async def test_unexpected_error_maps_to_internal_error_without_leaking_secrets() -> None:
    # The exception carries "secret DSN + API key + JWT" content that
    # must NOT appear in the outgoing frame.
    graph = _FakeGraph(raise_exc=RuntimeError("secretpwd sk-ant-XYZ eyJhaZ.jwt"))
    frames = await _drain(
        event_stream(
            graph=cast(Any, graph),
            initial_state={"question": "q", "tenant_id": "tenant-a", "request_id": "r"},
            thread_id="thread-1",
        )
    )
    channel, payload = _decode(frames[0])
    assert channel == "3"
    assert payload == "internal_error"
    for leak in ("secretpwd", "sk-ant-XYZ", "eyJhaZ.jwt", "RuntimeError"):
        assert leak.encode() not in frames[0]


# ---------- Cancellation ----------


@pytest.mark.asyncio
async def test_cancelled_error_is_not_converted_to_internal_error() -> None:
    graph = _FakeGraph(raise_exc=asyncio.CancelledError())
    with pytest.raises(asyncio.CancelledError):
        # Fully drain — the CancelledError must propagate out.
        async for _ in event_stream(
            graph=cast(Any, graph),
            initial_state={"question": "q", "tenant_id": "tenant-a", "request_id": "r"},
            thread_id="thread-1",
        ):
            pass


# ---------- Invocation config threading ----------


@pytest.mark.asyncio
async def test_graph_receives_invocation_config_with_recursion_limit() -> None:
    final = {"text": "ok", "citations": [], "confidence": 0.7}
    graph = _FakeGraph([_synth_end_event(final)])
    await _drain(
        event_stream(
            graph=cast(Any, graph),
            initial_state={
                "question": "q",
                "tenant_id": "tenant-a",
                "request_id": "r",
                "thread_id": "thread-carrier",
            },
            thread_id="thread-carrier",
        )
    )
    cfg = graph.received_config
    assert isinstance(cfg, Mapping)
    assert cfg["recursion_limit"] == 25
    configurable = cfg["configurable"]
    assert isinstance(configurable, Mapping)
    assert configurable["thread_id"] == "thread-carrier"


@pytest.mark.asyncio
async def test_initial_state_carries_request_id_but_no_non_serializable_objects() -> None:
    final = {"text": "ok", "citations": [], "confidence": 0.7}
    graph = _FakeGraph([_synth_end_event(final)])
    initial = {
        "question": "q",
        "tenant_id": "tenant-a",
        "request_id": "req-opaque",
        "thread_id": "thread-1",
    }
    await _drain(
        event_stream(
            graph=cast(Any, graph),
            initial_state=initial,
            thread_id="thread-1",
        )
    )
    seen = graph.received_input
    assert isinstance(seen, dict)
    assert seen["request_id"] == "req-opaque"
    # And nothing callable / MCP-shaped / budget-shaped landed on the state.
    for value in seen.values():
        assert not callable(value)
        module = type(value).__module__
        assert not module.startswith("asyncio")
        assert not module.startswith("psycopg")


# ---------- Fallback path ----------


@pytest.mark.asyncio
async def test_fallback_text_emitted_once_when_no_deltas() -> None:
    """Instructor structured output produces no chat-model deltas; the
    fallback must ship the final text on channel 0 exactly once."""
    final = {"text": "the final synthesized text", "citations": [], "confidence": 0.5}
    graph = _FakeGraph([_synth_end_event(final)])
    frames = await _drain(
        event_stream(
            graph=cast(Any, graph),
            initial_state={"question": "q", "tenant_id": "tenant-a", "request_id": "r"},
            thread_id="thread-1",
        )
    )
    text_frames = [f for f in frames if f.startswith(b"0:")]
    assert len(text_frames) == 1
    assert json.loads(text_frames[0].decode()[2:]) == "the final synthesized text"


@pytest.mark.asyncio
async def test_content_block_list_dict_shape_extracted() -> None:
    """Anthropic tool-use content shows as list[dict]; walk that path."""

    class _ChunkListDict:
        def __init__(self) -> None:
            self.content = [
                {"text": "hello"},
                {"type": "tool_use"},
                {"text": " world"},
            ]

    ev = {
        "event": "on_chat_model_stream",
        "metadata": {"langgraph_node": "synthesis_agent"},
        "data": {"chunk": _ChunkListDict()},
    }
    final = {"text": "hello world", "citations": [], "confidence": 0.5}
    graph = _FakeGraph([ev, _synth_end_event(final)])
    frames = await _drain(
        event_stream(
            graph=cast(Any, graph),
            initial_state={"question": "q", "tenant_id": "tenant-a", "request_id": "r"},
            thread_id="thread-1",
        )
    )
    decoded = [_decode(f) for f in frames]
    text = "".join(str(v) for c, v in decoded if c == "0")
    assert "hello world" in text


@pytest.mark.asyncio
async def test_content_block_list_object_shape_extracted() -> None:
    """LangChain BaseMessageChunk may hold list[object with .text]."""

    class _Block:
        def __init__(self, text: str) -> None:
            self.text = text

    class _ChunkListObj:
        def __init__(self) -> None:
            self.content = [_Block("A"), _Block("B")]

    ev = {
        "event": "on_chat_model_stream",
        "metadata": {"langgraph_node": "synthesis_agent"},
        "data": {"chunk": _ChunkListObj()},
    }
    final = {"text": "AB", "citations": [], "confidence": 0.5}
    graph = _FakeGraph([ev, _synth_end_event(final)])
    frames = await _drain(
        event_stream(
            graph=cast(Any, graph),
            initial_state={"question": "q", "tenant_id": "tenant-a", "request_id": "r"},
            thread_id="thread-1",
        )
    )
    decoded = [_decode(f) for f in frames]
    text = "".join(str(v) for c, v in decoded if c == "0")
    assert "AB" in text


@pytest.mark.asyncio
async def test_synthesis_end_without_final_answer_uses_answer_fallback() -> None:
    """When ``final_answer`` is absent but ``answer`` is set, adapt it."""
    ev = {
        "event": "on_chain_end",
        "name": "synthesis_agent",
        "metadata": {"langgraph_node": "synthesis_agent"},
        "data": {"output": {"answer": "just an answer string"}},
    }
    graph = _FakeGraph([ev])
    frames = await _drain(
        event_stream(
            graph=cast(Any, graph),
            initial_state={"question": "q", "tenant_id": "tenant-a", "request_id": "r"},
            thread_id="thread-1",
        )
    )
    decoded = [_decode(f) for f in frames]
    channels = [c for c, _ in decoded]
    assert channels == ["0", "2"]
    # The channel-2 payload is a one-element array; the wrapped
    # FinalAnswer was normalised.
    payload_list = decoded[-1][1]
    assert isinstance(payload_list, list) and len(payload_list) == 1
    payload = payload_list[0]
    assert isinstance(payload, dict)
    assert payload["text"] == "just an answer string"


@pytest.mark.asyncio
async def test_synthesis_end_event_with_no_output_is_ignored() -> None:
    ev = {
        "event": "on_chain_end",
        "name": "synthesis_agent",
        "metadata": {"langgraph_node": "synthesis_agent"},
        "data": {},
    }
    graph = _FakeGraph([ev])
    frames = await _drain(
        event_stream(
            graph=cast(Any, graph),
            initial_state={"question": "q", "tenant_id": "tenant-a", "request_id": "r"},
            thread_id="thread-1",
        )
    )
    assert frames == []


@pytest.mark.asyncio
async def test_malformed_final_answer_is_normalised_safely() -> None:
    """A final_answer payload that fails FinalAnswer validation is coerced
    into a safe shape rather than raising."""
    ev = _synth_end_event(
        {
            # Missing "citations" and wrong "confidence" — the strict
            # FinalAnswer model would reject this; our normaliser
            # produces a safe channel-2 body.
            "text": "half-broken answer",
            "confidence": 2.5,  # out of range
        }
    )
    graph = _FakeGraph([ev])
    frames = await _drain(
        event_stream(
            graph=cast(Any, graph),
            initial_state={"question": "q", "tenant_id": "tenant-a", "request_id": "r"},
            thread_id="thread-1",
        )
    )
    payload_list = _decode(frames[-1])[1]
    assert isinstance(payload_list, list) and len(payload_list) == 1
    payload = payload_list[0]
    assert isinstance(payload, dict)
    assert payload["text"] == "half-broken answer"
    conf = payload["confidence"]
    assert isinstance(conf, (int, float))
    assert 0.0 <= conf <= 1.0


def test_error_frame_for_unknown_code_falls_back_to_internal_error() -> None:
    frame = error_frame_for("nope-not-a-real-code")
    channel, payload = _decode(frame)
    assert channel == "3"
    assert payload == "internal_error"
