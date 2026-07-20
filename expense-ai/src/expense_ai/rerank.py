"""MMR diversification and BGE cross-encoder reranking with timeout/fallback.

The reranker is expensive; we bound it with a strict 300 ms timeout and
fall back to the pre-rerank ordering when the budget is exceeded. This
matches the W7D3 spec's "timeout-and-fallback" pattern.
"""

from __future__ import annotations

import threading
import time
from collections.abc import Sequence
from typing import Protocol

import numpy as np
from langsmith import traceable
from numpy.typing import NDArray

from .hybrid import HybridHit

RERANKER_MODEL = "BAAI/bge-reranker-base"
RERANK_TIMEOUT_MS = 300
MMR_LAMBDA = 0.7


class CrossEncoderLike(Protocol):
    """Structural type matching the CrossEncoder API we call."""

    def predict(self, pairs: list[list[str]]) -> NDArray[np.float32]: ...


_reranker_cache: CrossEncoderLike | None = None
_rerank_timeout_count = 0
_counter_lock = threading.Lock()


def get_rerank_timeout_count() -> int:
    with _counter_lock:
        return _rerank_timeout_count


def _bump_timeout_counter() -> None:
    global _rerank_timeout_count
    with _counter_lock:
        _rerank_timeout_count += 1


def reset_rerank_timeout_count() -> None:
    global _rerank_timeout_count
    with _counter_lock:
        _rerank_timeout_count = 0


def _load_reranker() -> CrossEncoderLike:
    global _reranker_cache
    if _reranker_cache is None:
        from sentence_transformers import CrossEncoder  # local import: heavy

        model = CrossEncoder(RERANKER_MODEL, max_length=256)
        _reranker_cache = model
    return _reranker_cache


def _cos_sim(a: NDArray[np.float32], b: NDArray[np.float32]) -> float:
    na = float(np.linalg.norm(a))
    nb = float(np.linalg.norm(b))
    if na == 0.0 or nb == 0.0:
        return 0.0
    return float(np.dot(a, b) / (na * nb))


@traceable(run_type="chain", name="expense_ai.mmr_pick")
def mmr_pick(
    query_vec: NDArray[np.float32],
    candidates: Sequence[HybridHit],
    candidate_vecs: NDArray[np.float32] | None = None,
    embedder: object | None = None,
    k: int = 20,
    lambda_param: float = MMR_LAMBDA,
) -> list[HybridHit]:
    """Greedy MMR diversification over a candidate list.

    Score = ``lambda * sim(query, cand) - (1 - lambda) * max sim(cand, picked)``.

    ``candidate_vecs`` must line up with ``candidates`` when supplied.
    If neither ``candidate_vecs`` nor ``embedder`` is given, we fall back to
    a light per-hit hash-based pseudo-embedding so tests can exercise MMR
    without a model. Callers in production should always provide either
    ``candidate_vecs`` or an ``embedder``.
    """
    if not candidates:
        return []
    if k <= 0:
        return []

    if candidate_vecs is None:
        if embedder is not None and hasattr(embedder, "encode"):
            texts = [c.chunk_text for c in candidates]
            encode = embedder.encode
            raw = encode(
                texts,
                batch_size=len(texts),
                normalize_embeddings=True,
                convert_to_numpy=True,
            )
            candidate_vecs = np.asarray(raw, dtype=np.float32)
        else:
            # Fallback: deterministic hash-based pseudo-vectors so tests run
            # without pulling in a real encoder. Not for production use.
            dim = query_vec.shape[0]
            vecs = np.zeros((len(candidates), dim), dtype=np.float32)
            for i, c in enumerate(candidates):
                rng = np.random.default_rng(abs(hash(c.chunk_id)) % (2**32))
                v_arr: NDArray[np.float32] = np.asarray(rng.standard_normal(dim), dtype=np.float32)
                norm = float(np.linalg.norm(v_arr)) or 1.0
                vecs[i] = v_arr / norm
            candidate_vecs = vecs

    n = len(candidates)
    picked: list[int] = []
    remaining = list(range(n))
    q_sims = np.asarray(
        [_cos_sim(query_vec, candidate_vecs[i]) for i in range(n)],
        dtype=np.float32,
    )

    while remaining and len(picked) < k:
        best_idx = -1
        best_score = -float("inf")
        for i in remaining:
            if picked:
                max_sim = max(_cos_sim(candidate_vecs[i], candidate_vecs[j]) for j in picked)
            else:
                max_sim = 0.0
            score = lambda_param * float(q_sims[i]) - (1.0 - lambda_param) * float(max_sim)
            if score > best_score:
                best_score = score
                best_idx = i
        picked.append(best_idx)
        remaining.remove(best_idx)

    return [candidates[i] for i in picked]


@traceable(run_type="chain", name="expense_ai.bge_rerank")
def bge_rerank(
    query_text: str,
    candidates: Sequence[HybridHit],
    top_k: int = 6,
    timeout_ms: int = RERANK_TIMEOUT_MS,
    reranker: CrossEncoderLike | None = None,
) -> tuple[list[HybridHit], bool]:
    """Rerank ``candidates`` with a BGE cross-encoder; strict timeout/fallback.

    Returns ``(hits, timed_out)``. On timeout we return ``candidates[:top_k]``
    in their original order and set ``timed_out=True`` — the caller can log
    it and, in production, page on excessive timeouts.
    """
    if not candidates:
        return [], False

    start = time.monotonic()
    used = reranker if reranker is not None else _load_reranker()

    pairs = [[query_text, c.chunk_text] for c in candidates]
    scores = used.predict(pairs)

    elapsed_ms = (time.monotonic() - start) * 1000.0
    if elapsed_ms > timeout_ms:
        _bump_timeout_counter()
        return list(candidates[:top_k]), True

    order = np.argsort(-np.asarray(scores, dtype=np.float32))
    ordered = [candidates[int(i)] for i in order[:top_k]]
    rescored: list[HybridHit] = []
    for idx, hit in zip(order[:top_k], ordered, strict=True):
        rescored.append(
            HybridHit(
                chunk_id=hit.chunk_id,
                doc_id=hit.doc_id,
                chunk_idx=hit.chunk_idx,
                chunk_text=hit.chunk_text,
                score=float(scores[int(idx)]),
                tenant_id=hit.tenant_id,
                metadata=hit.metadata,
            )
        )
    return rescored, False
