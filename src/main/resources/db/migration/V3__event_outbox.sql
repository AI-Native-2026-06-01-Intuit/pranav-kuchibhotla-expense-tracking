-- V3__event_outbox.sql
-- Transactional outbox for domain events (Week 3 Day 3 Task 1).
-- Rows are inserted in the same transaction as the domain write; a
-- scheduled publisher polls unpublished rows and ships them to Kafka.

CREATE TABLE IF NOT EXISTS expense.event_outbox (
    id           UUID         PRIMARY KEY DEFAULT gen_random_uuid(),
    aggregate_id TEXT         NOT NULL,
    topic        TEXT         NOT NULL,
    payload      JSONB        NOT NULL,
    occurred_at  TIMESTAMPTZ  NOT NULL DEFAULT NOW(),
    published_at TIMESTAMPTZ  NULL
);

-- Partial index: only rows still awaiting publication are indexed, so
-- the publisher's `WHERE published_at IS NULL ORDER BY occurred_at`
-- scan stays bounded as published rows accumulate.
CREATE INDEX IF NOT EXISTS idx_event_outbox_unpublished
    ON expense.event_outbox (occurred_at)
    WHERE published_at IS NULL;
