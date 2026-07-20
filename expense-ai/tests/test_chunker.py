"""Tests for the recursive-character chunker."""

from __future__ import annotations

import pytest
from langchain_core.documents import Document

from expense_ai.chunker import (
    DEFAULT_CHUNK_SIZE,
    DEFAULT_OVERLAP,
    chunk_docs,
    make_splitter,
)


def test_make_splitter_rejects_overlap_ge_half_chunk() -> None:
    with pytest.raises(ValueError):
        make_splitter(chunk_size=100, overlap=200)


def test_make_splitter_rejects_negative_overlap() -> None:
    with pytest.raises(ValueError):
        make_splitter(chunk_size=100, overlap=-1)


def test_default_splitter_is_valid() -> None:
    splitter = make_splitter()
    assert splitter is not None
    # sanity: defaults obey the constraint
    assert 0 <= DEFAULT_OVERLAP < DEFAULT_CHUNK_SIZE / 2


def _five_kb_doc() -> Document:
    # ~5 KB of realistic prose (paragraphs so recursive separators kick in).
    paragraph = (
        "Schedule C filers deduct ordinary and necessary business expenses "
        "including mileage at the standard IRS rate, home office pro-rata, "
        "and depreciation on capitalized assets over their useful life. "
    )
    text = "\n\n".join([f"Section {i}. {paragraph * 3}" for i in range(20)])
    return Document(
        page_content=text[:5000],
        metadata={"doc_id": "sched-c-101", "tenant_id": "tenant-a", "category": "irs"},
    )


def test_chunk_ids_stable_and_monotonic() -> None:
    doc = _five_kb_doc()
    chunks = chunk_docs([doc])
    assert len(chunks) >= 2
    for i, chunk in enumerate(chunks):
        assert chunk.metadata["chunk_id"] == f"chunk-sched-c-101-p{i}"
        assert chunk.metadata["chunk_ordinal"] == i
        assert chunk.metadata["source_doc_id"] == "sched-c-101"


def test_chunk_length_within_bounds() -> None:
    doc = _five_kb_doc()
    chunks = chunk_docs([doc])
    lengths = [len(c.page_content) for c in chunks]
    avg = sum(lengths) / len(lengths)
    assert 400 <= avg <= 950, f"average chunk length {avg} outside [400, 950]"


def test_metadata_preserved_from_source() -> None:
    doc = _five_kb_doc()
    chunks = chunk_docs([doc])
    for chunk in chunks:
        assert chunk.metadata["tenant_id"] == "tenant-a"
        assert chunk.metadata["category"] == "irs"


def test_chunk_ids_namespaced_per_doc() -> None:
    doc_a = Document(
        page_content="alpha " * 300,
        metadata={"doc_id": "doc-A"},
    )
    doc_b = Document(
        page_content="beta " * 300,
        metadata={"doc_id": "doc-B"},
    )
    chunks = chunk_docs([doc_a, doc_b])
    ids_a = [c.metadata["chunk_id"] for c in chunks if c.metadata["source_doc_id"] == "doc-A"]
    ids_b = [c.metadata["chunk_id"] for c in chunks if c.metadata["source_doc_id"] == "doc-B"]
    assert ids_a[0] == "chunk-doc-A-p0"
    assert ids_b[0] == "chunk-doc-B-p0"


def test_missing_doc_id_raises() -> None:
    with pytest.raises(ValueError):
        chunk_docs([Document(page_content="text", metadata={})])
