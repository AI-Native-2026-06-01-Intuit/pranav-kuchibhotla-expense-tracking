"""Tests for the pandas corpus loader and MiniLM embedding pass."""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pandas as pd
import pytest
from numpy.typing import NDArray

from expense_ai.corpus import (
    EMBEDDING_DIM,
    MODEL_NAME,
    CorpusRow,
    embed_dataframe,
    load_corpus,
)


class _FakeEncoder:
    """Deterministic encoder that avoids downloading real MiniLM weights."""

    def __init__(self, dim: int = EMBEDDING_DIM) -> None:
        self._dim = dim

    def encode(
        self,
        sentences: list[str],
        batch_size: int = 64,
        normalize_embeddings: bool = True,
        convert_to_numpy: bool = True,
    ) -> NDArray[np.float32]:
        n = len(sentences)
        rng = np.random.default_rng(seed=42)
        mat = rng.standard_normal((n, self._dim)).astype(np.float32)
        if normalize_embeddings:
            norms = np.linalg.norm(mat, axis=1, keepdims=True)
            norms[norms == 0.0] = 1.0
            mat = (mat / norms).astype(np.float32)
        return mat


def _write_jsonl(path: Path, rows: list[dict[str, object]]) -> None:
    with path.open("w") as fh:
        for row in rows:
            fh.write(json.dumps(row) + "\n")


def test_load_corpus_dedups_on_doc_id_and_chunk_idx(tmp_path: Path) -> None:
    path = tmp_path / "corpus.jsonl"
    _write_jsonl(
        path,
        [
            {"doc_id": "d1", "chunk_idx": 0, "chunk_text": "first", "tenant_id": "tenant-a"},
            {"doc_id": "d1", "chunk_idx": 0, "chunk_text": "dup", "tenant_id": "tenant-a"},
            {"doc_id": "d1", "chunk_idx": 1, "chunk_text": "second", "tenant_id": "tenant-a"},
            {"doc_id": "d2", "chunk_idx": 0, "chunk_text": "other", "tenant_id": "tenant-b"},
        ],
    )
    df = load_corpus(path)
    assert len(df) == 3
    first = df[(df["doc_id"] == "d1") & (df["chunk_idx"] == 0)].iloc[0]
    assert first["chunk_text"] == "first"


@pytest.mark.parametrize(
    ("bad_text", "expected_kept"),
    [
        ("", False),
        ("x" * 8001, False),
        ("normal", True),
    ],
)
def test_load_corpus_filters_by_length(tmp_path: Path, bad_text: str, expected_kept: bool) -> None:
    path = tmp_path / "corpus.jsonl"
    _write_jsonl(
        path,
        [{"doc_id": "d1", "chunk_idx": 0, "chunk_text": bad_text, "tenant_id": "tenant-a"}],
    )
    df = load_corpus(path)
    assert (len(df) == 1) is expected_kept


def test_load_corpus_missing_column_raises(tmp_path: Path) -> None:
    path = tmp_path / "corpus.jsonl"
    _write_jsonl(
        path,
        [{"doc_id": "d1", "chunk_idx": 0, "chunk_text": "hi"}],
    )
    with pytest.raises(ValueError, match="missing required columns"):
        load_corpus(path)


def test_load_corpus_unsupported_extension_raises(tmp_path: Path) -> None:
    path = tmp_path / "corpus.txt"
    path.write_text("not json")
    with pytest.raises(ValueError, match="Unsupported corpus extension"):
        load_corpus(path)


def test_embed_dataframe_produces_float32_384(tmp_path: Path) -> None:
    df = pd.DataFrame(
        [
            {"doc_id": "d1", "chunk_idx": 0, "chunk_text": "hello", "tenant_id": "tenant-a"},
            {"doc_id": "d2", "chunk_idx": 0, "chunk_text": "world", "tenant_id": "tenant-b"},
        ]
    )
    rows = embed_dataframe(df, model=_FakeEncoder())
    assert len(rows) == 2
    for row in rows:
        assert isinstance(row, CorpusRow)
        assert row.embedding.dtype == np.float32
        assert row.embedding.shape == (EMBEDDING_DIM,)
        assert row.model_version == MODEL_NAME


def test_embed_dataframe_wrong_shape_raises() -> None:
    df = pd.DataFrame(
        [{"doc_id": "d1", "chunk_idx": 0, "chunk_text": "x", "tenant_id": "tenant-a"}]
    )

    class _WrongDim:
        def encode(
            self,
            sentences: list[str],
            batch_size: int = 64,
            normalize_embeddings: bool = True,
            convert_to_numpy: bool = True,
        ) -> NDArray[np.float32]:
            return np.zeros((len(sentences), 16), dtype=np.float32)

    with pytest.raises(ValueError, match="does not match expected"):
        embed_dataframe(df, model=_WrongDim())


def test_load_corpus_seed_fixture_shape() -> None:
    fixture = Path(__file__).parent / "fixtures" / "corpus_seed.jsonl"
    df = load_corpus(fixture)
    assert len(df) >= 100
    assert set(df["tenant_id"].unique()).issubset({"tenant-a", "tenant-b", "tenant-c"})
