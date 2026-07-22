-- V5__orders_refunds.sql
-- Synthetic order/refund surface (W7D4 prerequisite gap).
-- The rubric assumes a W3D1 expense-orders service; the capstone repo does
-- not ship one. We add the smallest tenant-scoped surface here so the MCP
-- adapter can publish orders.get_order + orders.create_refund against real
-- Spring endpoints and prove idempotent refund semantics end-to-end.

CREATE SCHEMA IF NOT EXISTS expense;

CREATE TABLE IF NOT EXISTS expense.synthetic_order (
    id            TEXT           NOT NULL,
    tenant_id     TEXT           NOT NULL,
    total_amount  NUMERIC(12, 2) NOT NULL,
    status        TEXT           NOT NULL,
    created_at    TIMESTAMPTZ    NOT NULL DEFAULT NOW(),

    CONSTRAINT synthetic_order_pkey PRIMARY KEY (id),
    CONSTRAINT synthetic_order_tenant_not_blank
        CHECK (length(tenant_id) > 0),
    CONSTRAINT synthetic_order_total_nonneg
        CHECK (total_amount >= 0),
    CONSTRAINT synthetic_order_status_allowed
        CHECK (status IN ('OPEN', 'REFUNDED', 'PARTIALLY_REFUNDED', 'CANCELLED'))
);

CREATE INDEX IF NOT EXISTS idx_synthetic_order_tenant
    ON expense.synthetic_order (tenant_id);

CREATE TABLE IF NOT EXISTS expense.synthetic_refund (
    id               TEXT           NOT NULL,
    order_id         TEXT           NOT NULL,
    tenant_id        TEXT           NOT NULL,
    amount           NUMERIC(12, 2) NOT NULL,
    reason           TEXT           NOT NULL,
    status           TEXT           NOT NULL,
    idempotency_key  TEXT           NOT NULL,
    created_at       TIMESTAMPTZ    NOT NULL DEFAULT NOW(),

    CONSTRAINT synthetic_refund_pkey PRIMARY KEY (id),
    CONSTRAINT synthetic_refund_order_fk
        FOREIGN KEY (order_id) REFERENCES expense.synthetic_order (id),
    CONSTRAINT synthetic_refund_amount_pos
        CHECK (amount > 0),
    CONSTRAINT synthetic_refund_status_allowed
        CHECK (status IN ('PENDING', 'SETTLED', 'FAILED')),
    -- Idempotency invariant: the same (order, key) must produce the same
    -- refund_id, so a duplicate insert is rejected at the storage layer.
    CONSTRAINT synthetic_refund_order_key_unique
        UNIQUE (order_id, idempotency_key)
);

CREATE INDEX IF NOT EXISTS idx_synthetic_refund_tenant
    ON expense.synthetic_refund (tenant_id);

-- Seed synthetic order used by the W7D4 Testcontainers E2E.
INSERT INTO expense.synthetic_order (id, tenant_id, total_amount, status)
    VALUES ('ord-synth-9001', 'tenant-a', 129.99, 'OPEN')
ON CONFLICT (id) DO NOTHING;
