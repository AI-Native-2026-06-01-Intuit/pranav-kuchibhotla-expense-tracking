-- V002__rag2_metadata_and_partial_indexes.sql
--
-- RAG 2.0 additions on top of V001:
--   * chunk_metadata jsonb: per-chunk facets (category, source_system,
--     effective_date, etc.). GIN jsonb_path_ops supports the @> containment
--     operator we use for metadata filtering in
--     ``expense_ai.hybrid.dense_topk_filtered`` / ``sparse_topk_fts``.
--   * content_hash: sha256 of chunk_text. Lets the ingestion pipeline gate
--     the embedding call in ``needs_embedding()`` — DB ON CONFLICT still
--     handles idempotent writes, but we skip the expensive model call when
--     stored content hasn't changed.
--   * chunk_tsv: STORED tsvector, keeps FTS ranking cheap and lets us
--     GIN-index the tsvector directly.
--   * Per-tenant partial HNSW indexes on (tenant-a|b|c). Combined with the
--     ``WHERE tenant_id = %s`` filter in the retrieval SQL, these give
--     DB-side tenant isolation: even a leaked application filter cannot
--     surface another tenant's rows through the ANN index. HNSW uses
--     ``vector_cosine_ops`` to match the ``<=>`` cosine-distance query
--     operator.
--
-- All indexes are CREATE INDEX CONCURRENTLY IF NOT EXISTS. Postgres will
-- reject CREATE INDEX CONCURRENTLY inside a transaction block, so callers
-- must run this file in autocommit mode (or split it out). See
-- ``tests/_pg_wait.py`` and the per-test schema helper for the pattern.

ALTER TABLE doc_chunks
    ADD COLUMN IF NOT EXISTS chunk_metadata jsonb NOT NULL DEFAULT '{}'::jsonb;

ALTER TABLE doc_chunks
    ADD COLUMN IF NOT EXISTS content_hash text;

ALTER TABLE doc_chunks
    ADD COLUMN IF NOT EXISTS chunk_tsv tsvector
        GENERATED ALWAYS AS (to_tsvector('english', chunk_text)) STORED;

-- GIN jsonb_path_ops supports the @> containment operator we use to filter
-- metadata (e.g., WHERE chunk_metadata @> '{"category":"schedule_c"}').
CREATE INDEX CONCURRENTLY IF NOT EXISTS doc_chunks_chunk_metadata_gin
    ON doc_chunks
    USING gin (chunk_metadata jsonb_path_ops);

-- FTS GIN index on the generated tsvector column.
CREATE INDEX CONCURRENTLY IF NOT EXISTS doc_chunks_chunk_tsv_gin
    ON doc_chunks
    USING gin (chunk_tsv);

-- Per-tenant partial HNSW indexes. Partial + WHERE tenant_id filter gives
-- DB-side tenant isolation. HNSW op class must match the query operator:
-- vector_cosine_ops matches <=> cosine distance.
CREATE INDEX CONCURRENTLY IF NOT EXISTS doc_chunks_embedding_hnsw_tenant_a
    ON doc_chunks
    USING hnsw (embedding vector_cosine_ops)
    WITH (m = 24, ef_construction = 128)
    WHERE tenant_id = 'tenant-a';

CREATE INDEX CONCURRENTLY IF NOT EXISTS doc_chunks_embedding_hnsw_tenant_b
    ON doc_chunks
    USING hnsw (embedding vector_cosine_ops)
    WITH (m = 24, ef_construction = 128)
    WHERE tenant_id = 'tenant-b';

CREATE INDEX CONCURRENTLY IF NOT EXISTS doc_chunks_embedding_hnsw_tenant_c
    ON doc_chunks
    USING hnsw (embedding vector_cosine_ops)
    WITH (m = 24, ef_construction = 128)
    WHERE tenant_id = 'tenant-c';
