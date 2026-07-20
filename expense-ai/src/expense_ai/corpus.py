"""Corpus loading and MiniLM embedding for the expense-ai RAG pipeline.

Loads a synthetic Schedule C / expense-deduction corpus from disk, validates
its shape, and produces 384-dim MiniLM sentence-transformer embeddings in
strict ``np.float32`` — the same dtype the pgvector column expects.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Protocol, cast

import numpy as np
import pandas as pd
from numpy.typing import NDArray

MODEL_NAME = "all-MiniLM-L6-v2"
EMBEDDING_DIM = 384

_REQUIRED_COLUMNS = ("doc_id", "chunk_idx", "chunk_text", "tenant_id")
_MIN_CHUNK_LEN = 1
_MAX_CHUNK_LEN = 8000


@dataclass(frozen=True, slots=True)
class CorpusRow:
    """One embedded chunk ready for pgvector insertion."""

    doc_id: str
    chunk_idx: int
    chunk_text: str
    embedding: NDArray[np.float32]
    model_version: str
    tenant_id: str


class _EncoderLike(Protocol):
    """Minimal structural type for a SentenceTransformer-shaped encoder.

    We type only what we call, so tests can inject a deterministic fake without
    depending on the real sentence-transformers class.
    """

    def encode(
        self,
        sentences: list[str],
        batch_size: int = ...,
        normalize_embeddings: bool = ...,
        convert_to_numpy: bool = ...,
    ) -> NDArray[np.float32]: ...


def load_corpus(path: Path) -> pd.DataFrame:
    """Load a corpus file, validate, dedup, and length-filter.

    Supports ``.jsonl``, ``.json``, ``.parquet``. Raises ``ValueError`` on
    unsupported extension, missing required columns, or empty result.
    """
    suffix = path.suffix.lower()
    if suffix == ".jsonl":
        df = pd.read_json(path, lines=True)
    elif suffix == ".json":
        df = pd.read_json(path)
    elif suffix == ".parquet":
        df = pd.read_parquet(path)
    else:
        raise ValueError(
            f"Unsupported corpus extension {suffix!r} (expected .jsonl, .json, .parquet)"
        )

    missing = [c for c in _REQUIRED_COLUMNS if c not in df.columns]
    if missing:
        raise ValueError(f"Corpus missing required columns: {missing}")

    df = df.drop_duplicates(subset=["doc_id", "chunk_idx"], keep="first")

    text_len = df["chunk_text"].astype(str).str.len()
    df = df.loc[(text_len >= _MIN_CHUNK_LEN) & (text_len <= _MAX_CHUNK_LEN)]

    return df.reset_index(drop=True)


def embed_dataframe(
    df: pd.DataFrame,
    model: _EncoderLike | None = None,
    batch_size: int = 64,
) -> list[CorpusRow]:
    """Embed each ``chunk_text`` row into a 384-dim ``np.float32`` vector.

    ``model`` may be injected for tests; when ``None``, the real
    ``SentenceTransformer(MODEL_NAME)`` is loaded lazily so unit tests do not
    pay the model-download cost.
    """
    if model is None:
        from sentence_transformers import SentenceTransformer

        model = cast(_EncoderLike, SentenceTransformer(MODEL_NAME))

    texts = df["chunk_text"].astype(str).tolist()
    raw = model.encode(
        texts,
        batch_size=batch_size,
        normalize_embeddings=True,
        convert_to_numpy=True,
    )
    matrix = np.asarray(raw, dtype=np.float32)

    expected_shape = (len(df), EMBEDDING_DIM)
    if matrix.shape != expected_shape:
        raise ValueError(
            f"Embedding matrix shape {matrix.shape} does not match expected {expected_shape}"
        )

    rows: list[CorpusRow] = []
    for i, record in enumerate(df.to_dict(orient="records")):
        emb = matrix[i]
        if emb.shape != (EMBEDDING_DIM,):
            raise ValueError(f"Row {i} embedding shape {emb.shape} != ({EMBEDDING_DIM},)")
        if emb.dtype != np.float32:
            raise ValueError(f"Row {i} embedding dtype {emb.dtype} != float32")
        rows.append(
            CorpusRow(
                doc_id=str(record["doc_id"]),
                chunk_idx=int(record["chunk_idx"]),
                chunk_text=str(record["chunk_text"]),
                embedding=emb,
                model_version=MODEL_NAME,
                tenant_id=str(record["tenant_id"]),
            )
        )
    return rows
