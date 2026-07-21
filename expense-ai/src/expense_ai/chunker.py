"""Recursive-character chunker for the expense-ai RAG ingestion path.

Wraps LangChain's ``RecursiveCharacterTextSplitter`` with sane defaults for
Schedule C / expense-deduction prose (900 chars, 150 overlap), and stamps
every produced chunk with a stable ``chunk_id`` derived from the source
``doc_id`` and its ordinal position.
"""

from __future__ import annotations

from collections.abc import Sequence

from langchain_core.documents import Document
from langchain_text_splitters import RecursiveCharacterTextSplitter

DEFAULT_CHUNK_SIZE = 900
DEFAULT_OVERLAP = 150

_SEPARATORS: list[str] = ["\n\n", "\n", ". ", " ", ""]


def make_splitter(
    chunk_size: int = DEFAULT_CHUNK_SIZE,
    overlap: int = DEFAULT_OVERLAP,
) -> RecursiveCharacterTextSplitter:
    """Build a ``RecursiveCharacterTextSplitter`` with expense-domain defaults.

    Raises ``ValueError`` unless ``0 <= overlap < chunk_size / 2`` — an
    overlap that meets or exceeds half the chunk size produces near-duplicate
    chunks and drives the RRF / MMR downstream stages toward redundant hits.
    """
    if overlap < 0 or overlap >= chunk_size / 2:
        raise ValueError(
            f"overlap must satisfy 0 <= overlap < chunk_size/2 "
            f"(got overlap={overlap}, chunk_size={chunk_size})"
        )
    return RecursiveCharacterTextSplitter(
        chunk_size=chunk_size,
        chunk_overlap=overlap,
        separators=_SEPARATORS,
        length_function=len,
    )


def _doc_id_of(doc: Document) -> str:
    raw = doc.metadata.get("doc_id") if doc.metadata else None
    if raw is None:
        raise ValueError("Document.metadata['doc_id'] is required for chunking")
    return str(raw)


def chunk_docs(
    docs: Sequence[Document],
    chunk_size: int = DEFAULT_CHUNK_SIZE,
    overlap: int = DEFAULT_OVERLAP,
) -> list[Document]:
    """Chunk each ``Document`` and stamp stable metadata onto each piece.

    The returned chunks preserve the source ``metadata`` (so tenant/category
    fields survive) and add:

    * ``chunk_id``       — ``f"chunk-{doc_id}-p{i}"``, stable per source doc
    * ``chunk_ordinal``  — the zero-based position within the source doc
    * ``source_doc_id``  — the original ``doc_id``

    ``chunk_id`` is monotonic per source document; positions do not reset
    across documents (each doc has its own namespace).
    """
    splitter = make_splitter(chunk_size=chunk_size, overlap=overlap)
    out: list[Document] = []
    for doc in docs:
        doc_id = _doc_id_of(doc)
        pieces = splitter.split_text(doc.page_content)
        for i, piece in enumerate(pieces):
            base_meta = dict(doc.metadata) if doc.metadata else {}
            base_meta.update(
                {
                    "chunk_id": f"chunk-{doc_id}-p{i}",
                    "chunk_ordinal": i,
                    "source_doc_id": doc_id,
                }
            )
            out.append(Document(page_content=piece, metadata=base_meta))
    return out
