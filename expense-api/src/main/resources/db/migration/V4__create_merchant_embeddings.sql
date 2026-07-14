-- V4__create_merchant_embeddings.sql
-- pgvector-backed nearest-neighbor index over merchant embeddings.
-- Feeds tenant-scoped merchant lookups from the LLM proxy path so a
-- categorize-expense request can find the closest prior merchant
-- without a full-table scan.
--
-- Vector dimension is 1024 (matches the current embedding model's
-- output size); tightening or relaxing that requires a schema
-- migration since pgvector's HNSW index is dimension-typed.
--
-- Index tuning: HNSW m=16, ef_construction=64 is the pgvector
-- documented "sensible default" for read-mostly workloads at our
-- expected corpus size. Higher m improves recall at the cost of a
-- larger index; the doc's tradeoff sweet spot is m=16 for corpora
-- in the hundreds of thousands. vector_cosine_ops matches the
-- distance operator used at query time (<=>).

CREATE EXTENSION IF NOT EXISTS vector;

-- The V1/V2 bootstrap migrations sit outside src/main/resources/db/migration
-- (see db/V1__schema.sql at the repo root). Guard with IF NOT EXISTS here
-- so a bare Flyway run — used by the pgvector Testcontainers IT — creates
-- the schema on demand without a chicken-and-egg dependency on V1.
CREATE SCHEMA IF NOT EXISTS expense;

CREATE TABLE IF NOT EXISTS expense.merchant_embeddings (
    id          UUID         PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id   TEXT         NOT NULL,
    embedding   vector(1024) NOT NULL,
    inserted_at TIMESTAMPTZ  NOT NULL DEFAULT NOW()
);

-- HNSW cosine index for nearest-neighbor queries.
CREATE INDEX IF NOT EXISTS idx_merchant_embeddings_hnsw_cosine
    ON expense.merchant_embeddings
    USING hnsw (embedding vector_cosine_ops)
    WITH (m = 16, ef_construction = 64);

-- Tenant filter is applied before/around the ANN scan; keep a plain
-- btree on tenant_id so the planner can short-circuit small tenants.
CREATE INDEX IF NOT EXISTS idx_merchant_embeddings_tenant
    ON expense.merchant_embeddings (tenant_id);
