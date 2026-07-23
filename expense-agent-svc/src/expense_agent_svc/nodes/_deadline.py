"""Per-node deadline decorator.

Each of the three worker nodes has its own wall-clock budget
(retrieval 3s, API 5s, synthesis 8s). If the node exceeds it we do
*not* fail the whole graph — we return a caller-supplied sentinel
partial state so the graph converges, the trace records the timeout,
and the fan-in reducer can preserve whatever the other branch produced.

Ordering rule (see call sites): ``@deadline(...)`` is the **outer**
wrapper and ``@traceable(...)`` sits directly on the function. The
deadline knows about the LangSmith run through an injected callback
(default: :mod:`langsmith.run_helpers`), so tests do not need any
LangSmith connection.
"""

from __future__ import annotations

import asyncio
import functools
from collections.abc import Awaitable, Callable, Mapping
from typing import Any


def _default_tag_current_run(metadata: dict[str, object]) -> None:
    """Attach ``metadata`` to the current LangSmith run when available.

    Failure is intentionally silent: metadata tagging is an
    observability nicety, not a correctness property. In particular
    ``ImportError`` (no langsmith installed) and any RuntimeError
    (no active run tree) are swallowed. Tests inject their own tagger
    to observe calls.
    """
    try:
        from langsmith.run_helpers import get_current_run_tree
    except ImportError:
        return
    try:
        run = get_current_run_tree()
    except Exception:
        return
    if run is None:
        return
    extras = getattr(run, "extra", None)
    if isinstance(extras, dict):
        existing = extras.get("metadata")
        if isinstance(existing, dict):
            existing.update(metadata)
        else:
            extras["metadata"] = dict(metadata)


AsyncNode = Callable[..., Awaitable[Mapping[str, object]]]


def deadline(
    seconds: float,
    sentinel: Mapping[str, object],
    *,
    tag_current_run: Callable[[dict[str, object]], None] | None = None,
) -> Callable[[AsyncNode], AsyncNode]:
    """Wrap an async node so it always returns within ``seconds``.

    Args:
        seconds: Wall-clock budget. Must be strictly positive.
        sentinel: Partial state to return on timeout. A fresh ``dict``
            copy is returned on each timeout so downstream reducers
            never share aliased mutable objects.
        tag_current_run: Injection point for the LangSmith metadata
            tagger; defaults to :func:`_default_tag_current_run`.

    On timeout, the sentinel copy is augmented with
    ``deadline_exceeded=True`` and ``deadline_limit_s=seconds`` (safe
    metadata only) and the same values are handed to the tagger.
    """
    if not isinstance(seconds, (int, float)) or isinstance(seconds, bool):
        raise TypeError("seconds must be a positive number")
    if seconds <= 0:
        raise ValueError("seconds must be > 0")

    tag = tag_current_run if tag_current_run is not None else _default_tag_current_run

    def _decorate(node: AsyncNode) -> AsyncNode:
        @functools.wraps(node)
        async def _wrapped(*args: Any, **kwargs: Any) -> Mapping[str, object]:
            try:
                return await asyncio.wait_for(node(*args, **kwargs), timeout=seconds)
            except TimeoutError:
                copy: dict[str, object] = dict(sentinel)
                copy["deadline_exceeded"] = True
                copy["deadline_limit_s"] = seconds
                tag(
                    {
                        "deadline_exceeded": True,
                        "deadline_limit_s": seconds,
                        "node": node.__name__,
                    }
                )
                return copy

        return _wrapped

    return _decorate
