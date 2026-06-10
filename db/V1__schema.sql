-- V1__schema.sql
-- Initial schema for the expense domain (Week 2 Day 1).
-- Conventions:
--   * TEXT for all identifiers (never SERIAL / BIGINT).
--   * NUMERIC(12,2) for money.
--   * TIMESTAMPTZ for all timestamps.
--   * TEXT + CHECK for enum-like values (no native Postgres ENUM).

CREATE SCHEMA IF NOT EXISTS expense;

-- Drop in dependency order so local reruns are clean.
-- `expense.transaction` references both other tables, so it goes first.
DROP TABLE IF EXISTS expense.transaction;
DROP TABLE IF EXISTS expense.rule;
DROP TABLE IF EXISTS expense.merchant;

-- ---------------------------------------------------------------------------
-- expense.merchant
-- One row per known merchant. `normalized_name` is the canonical key used
-- by ingestion / rule-matching code; `display_name` is what we show users.
-- ---------------------------------------------------------------------------
CREATE TABLE expense.merchant (
    id              TEXT        NOT NULL,
    display_name    TEXT        NOT NULL,
    normalized_name TEXT        NOT NULL,
    merchant_kind   TEXT        NOT NULL,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),

    CONSTRAINT merchant_pkey PRIMARY KEY (id),

    -- Natural key: two merchants must not share a normalized name, since the
    -- ingestion pipeline uses it for dedupe.
    CONSTRAINT merchant_normalized_name_unique UNIQUE (normalized_name),

    -- Display name is user-visible; reject empty/whitespace-only values.
    CONSTRAINT merchant_display_name_not_blank
        CHECK (length(display_name) > 0),

    -- Normalized name drives dedupe + rule matching, so it must be present.
    CONSTRAINT merchant_normalized_name_not_blank
        CHECK (length(normalized_name) > 0),

    -- Enum-like domain: BUSINESS / PERSONAL / UNKNOWN. Stored as TEXT (not
    -- a Postgres ENUM) so values can evolve via a migration, not DDL surgery.
    CONSTRAINT merchant_kind_allowed
        CHECK (merchant_kind IN ('BUSINESS', 'PERSONAL', 'UNKNOWN'))
);

-- ---------------------------------------------------------------------------
-- expense.rule
-- Classification rules, one row per rule. Mirrors the Week 1 classifier
-- strategy types so each Java strategy has a persisted counterpart.
-- ---------------------------------------------------------------------------
CREATE TABLE expense.rule (
    id              TEXT           NOT NULL,
    rule_name       TEXT           NOT NULL,
    rule_type       TEXT           NOT NULL,
    pattern         TEXT           NOT NULL,
    minimum_amount  NUMERIC(12, 2) NOT NULL,
    active          BOOLEAN        NOT NULL DEFAULT TRUE,
    created_at      TIMESTAMPTZ    NOT NULL DEFAULT NOW(),

    CONSTRAINT rule_pkey PRIMARY KEY (id),

    -- Rule name is the human-facing identifier (used in logs / admin UI),
    -- so it must be unique across the table.
    CONSTRAINT rule_name_unique UNIQUE (rule_name),

    -- Reject empty rule names; they would render as blanks in any UI.
    CONSTRAINT rule_name_not_blank
        CHECK (length(rule_name) > 0),

    -- A rule with no pattern can never match anything, so the column is
    -- required to be non-empty even though TEXT permits an empty string.
    CONSTRAINT rule_pattern_not_blank
        CHECK (length(pattern) > 0),

    -- Money is non-negative in this domain; negative thresholds make no
    -- sense for any of the strategy types below.
    CONSTRAINT rule_minimum_amount_non_negative
        CHECK (minimum_amount >= 0),

    -- Enum-like domain mirroring Week 1 classifier strategies. Adding a new
    -- strategy in Java requires a migration that extends this CHECK list.
    CONSTRAINT rule_type_allowed
        CHECK (rule_type IN (
            'AMOUNT_THRESHOLD',
            'MCC_CODE',
            'MERCHANT_NAME',
            'RECURRING_CHARGE'
        ))
);

-- ---------------------------------------------------------------------------
-- expense.transaction
-- One row per imported transaction. Always references a merchant; may
-- reference a matched rule once classification has run.
-- ---------------------------------------------------------------------------
CREATE TABLE expense.transaction (
    id                TEXT           NOT NULL,
    account_id        TEXT           NOT NULL,
    merchant_id       TEXT           NOT NULL,
    matched_rule_id   TEXT           NULL,
    amount            NUMERIC(12, 2) NOT NULL,
    transaction_kind  TEXT           NOT NULL,
    occurred_at       TIMESTAMPTZ    NOT NULL,
    -- Nullable: a transaction may have been ingested but not yet classified.
    classified_at     TIMESTAMPTZ    NULL,
    created_at        TIMESTAMPTZ    NOT NULL DEFAULT NOW(),

    CONSTRAINT transaction_pkey PRIMARY KEY (id),

    -- account_id is an opaque external identifier; require non-empty so we
    -- never persist a transaction that cannot be traced back to an account.
    CONSTRAINT transaction_account_id_not_blank
        CHECK (length(account_id) > 0),

    -- Amounts in this domain are non-negative (sign / direction is encoded
    -- via transaction_kind and downstream logic, not via the amount column).
    CONSTRAINT transaction_amount_non_negative
        CHECK (amount >= 0),

    -- Enum-like domain. UNCLASSIFIED is the initial state before the
    -- classifier has run; DEDUCTIBLE / NON_DEDUCTIBLE are terminal states.
    CONSTRAINT transaction_kind_allowed
        CHECK (transaction_kind IN (
            'DEDUCTIBLE',
            'NON_DEDUCTIBLE',
            'UNCLASSIFIED'
        )),

    -- Every transaction belongs to exactly one merchant. RESTRICT prevents
    -- deleting a merchant that still has transactions on file; we'd rather
    -- force the caller to deal with the data than silently orphan rows.
    CONSTRAINT transaction_merchant_fk
        FOREIGN KEY (merchant_id)
        REFERENCES expense.merchant (id)
        ON DELETE RESTRICT,

    -- matched_rule_id is nullable (unclassified / non-deductible rows have
    -- no rule). SET NULL lets us retire a rule without losing the
    -- historical transactions it previously matched.
    CONSTRAINT transaction_matched_rule_fk
        FOREIGN KEY (matched_rule_id)
        REFERENCES expense.rule (id)
        ON DELETE SET NULL
);
