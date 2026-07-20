-- V001__doc_chunks.sql
-- Schema for pgvector-backed doc chunk store used by the expense-ai RAG path.
--
-- The HNSW index uses vector_cosine_ops so it matches the <=> (cosine
-- distance) operator that the retrieval query in `expense_ai.rag` uses.
-- Any mismatch between the index opclass and the query operator would
-- silently fall back to a sequential scan.

CREATE EXTENSION IF NOT EXISTS vector;

CREATE TABLE IF NOT EXISTS doc_chunks (
    chunk_id      BIGSERIAL PRIMARY KEY,
    doc_id        TEXT NOT NULL,
    chunk_idx     INTEGER NOT NULL,
    chunk_text    TEXT NOT NULL,
    embedding     vector(384) NOT NULL,
    model_version TEXT NOT NULL,
    tenant_id     TEXT NOT NULL,
    created_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (doc_id, chunk_idx, model_version)
);

CREATE INDEX IF NOT EXISTS doc_chunks_doc_id_idx
    ON doc_chunks (doc_id);

CREATE INDEX IF NOT EXISTS doc_chunks_tenant_model_idx
    ON doc_chunks (tenant_id, model_version);

-- HNSW ANN index. vector_cosine_ops is required for the <=> cosine query
-- operator in expense_ai.rag.retrieve_chunks.
CREATE INDEX IF NOT EXISTS doc_chunks_embedding_hnsw
    ON doc_chunks
    USING hnsw (embedding vector_cosine_ops)
    WITH (m = 16, ef_construction = 64);
