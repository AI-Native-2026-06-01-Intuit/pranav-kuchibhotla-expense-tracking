"""MMR and BGE rerank tests. Reranker is injected — no BGE download."""

from __future__ import annotations

import numpy as np
import pytest
from numpy.typing import NDArray

from expense_ai.hybrid import HybridHit
from expense_ai.rerank import (
    bge_rerank,
    get_rerank_timeout_count,
    mmr_pick,
    reset_rerank_timeout_count,
)


def _hit(chunk_id: str, text: str = "") -> HybridHit:
    return HybridHit(
        chunk_id=chunk_id,
        doc_id=chunk_id,
        chunk_idx=0,
        chunk_text=text or chunk_id,
        score=1.0,
    )


def _unit_vec(vec: list[float]) -> NDArray[np.float32]:
    arr = np.asarray(vec, dtype=np.float32)
    norm = float(np.linalg.norm(arr)) or 1.0
    return (arr / norm).astype(np.float32)


def test_mmr_lambda_one_matches_cosine_order() -> None:
    query = _unit_vec([1.0, 0.0, 0.0])
    # Candidate vectors of decreasing cosine sim to query.
    candidate_vecs = np.stack(
        [
            _unit_vec([1.0, 0.0, 0.0]),  # a: sim=1.0
            _unit_vec([0.9, 0.1, 0.0]),  # b: high
            _unit_vec([0.7, 0.3, 0.0]),  # c: mid
            _unit_vec([0.0, 1.0, 0.0]),  # d: low
        ]
    )
    candidates = [_hit("a"), _hit("b"), _hit("c"), _hit("d")]
    picked = mmr_pick(query, candidates, candidate_vecs=candidate_vecs, k=4, lambda_param=1.0)
    assert [p.chunk_id for p in picked] == ["a", "b", "c", "d"]


def test_mmr_lambda_zero_diversifies() -> None:
    query = _unit_vec([1.0, 0.0, 0.0])
    # Two near-duplicates of "a" plus two orthogonal alternates.
    candidate_vecs = np.stack(
        [
            _unit_vec([1.0, 0.0, 0.0]),  # a
            _unit_vec([0.99, 0.01, 0.0]),  # a'
            _unit_vec([0.0, 1.0, 0.0]),  # b
            _unit_vec([0.0, 0.0, 1.0]),  # c
        ]
    )
    candidates = [_hit("a"), _hit("a-prime"), _hit("b"), _hit("c")]
    picked = mmr_pick(query, candidates, candidate_vecs=candidate_vecs, k=3, lambda_param=0.0)
    ids = [p.chunk_id for p in picked]
    # a-prime should not be picked next to a when lambda_param=0.
    if "a" in ids[:2]:
        assert "a-prime" not in ids[:2]


class _FakeReranker:
    """Injected cross-encoder for tests: scores rise with chunk index.

    We simulate the BGE bringing the gold chunk (index 5 in candidates)
    to the top by giving it the highest score.
    """

    def __init__(self, gold_idx: int) -> None:
        self.gold_idx = gold_idx

    def predict(self, pairs: list[list[str]]) -> NDArray[np.float32]:
        n = len(pairs)
        scores = np.linspace(0.1, 0.5, n, dtype=np.float32)
        scores[self.gold_idx] = 0.99
        return scores


def test_bge_rerank_lifts_gold_to_top_with_fake() -> None:
    candidates = [_hit(f"c{i}", text=f"body {i}") for i in range(6)]
    reranker = _FakeReranker(gold_idx=5)
    reset_rerank_timeout_count()
    result, timed_out = bge_rerank(
        "supplies deduction",
        candidates,
        top_k=3,
        timeout_ms=5000,
        reranker=reranker,
    )
    assert not timed_out
    assert result[0].chunk_id == "c5"
    assert len(result) == 3


class _SlowReranker:
    def predict(self, pairs: list[list[str]]) -> NDArray[np.float32]:
        import time as _time

        _time.sleep(0.05)
        return np.zeros(len(pairs), dtype=np.float32)


def test_bge_rerank_timeout_falls_back_and_bumps_counter() -> None:
    candidates = [_hit(f"c{i}") for i in range(6)]
    reset_rerank_timeout_count()
    result, timed_out = bge_rerank(
        "q",
        candidates,
        top_k=3,
        timeout_ms=1,
        reranker=_SlowReranker(),
    )
    assert timed_out is True
    assert [h.chunk_id for h in result] == ["c0", "c1", "c2"]
    assert get_rerank_timeout_count() >= 1


def test_bge_rerank_empty_candidates() -> None:
    result, timed_out = bge_rerank("q", [], top_k=6, reranker=_FakeReranker(gold_idx=0))
    assert result == []
    assert timed_out is False


@pytest.mark.parametrize("lam", [0.0, 0.3, 0.7, 1.0])
def test_mmr_returns_k_items(lam: float) -> None:
    query = _unit_vec([1.0, 0.0])
    cand_vecs = np.stack([_unit_vec([1.0, 0.0]), _unit_vec([0.0, 1.0]), _unit_vec([1.0, 1.0])])
    cands = [_hit(f"c{i}") for i in range(3)]
    picked = mmr_pick(query, cands, candidate_vecs=cand_vecs, k=2, lambda_param=lam)
    assert len(picked) == 2
