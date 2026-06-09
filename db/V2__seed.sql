-- V2__seed.sql
-- Synthetic seed data for the expense schema (Week 2 Day 1).
--
-- Re-running this file is intentionally NOT idempotent: a second run will
-- collide on primary keys and fail. That's the desired safety net during
-- bootstrapping -- if you need to reseed, drop and reapply V1__schema.sql.
--
-- All identifiers below are synthetic ("merch-2026-NNNN", "Example" names).
-- Do not replace with real company or customer data.

BEGIN;

-- ---------------------------------------------------------------------------
-- expense.merchant
-- 5 merchants spanning all three merchant_kind values (BUSINESS, PERSONAL,
-- UNKNOWN) so the CHECK constraint and downstream filters get real coverage.
-- ---------------------------------------------------------------------------
INSERT INTO expense.merchant (id, display_name, normalized_name, merchant_kind) VALUES
    ('merch-2026-0001', 'Office Supply Example', 'office_supply_example', 'BUSINESS'),
    ('merch-2026-0002', 'Cloud Tools Example',   'cloud_tools_example',   'BUSINESS'),
    ('merch-2026-0003', 'Grocery Example',       'grocery_example',       'PERSONAL'),
    ('merch-2026-0004', 'Fuel Example',          'fuel_example',          'BUSINESS'),
    ('merch-2026-0005', 'Unknown Example',       'unknown_example',       'UNKNOWN');

-- ---------------------------------------------------------------------------
-- expense.rule
-- 5 rules covering every rule_type plus one inactive rule, so queries can
-- exercise both the type CHECK and the active=false filter path.
-- ---------------------------------------------------------------------------
INSERT INTO expense.rule (id, rule_name, rule_type, pattern, minimum_amount, active) VALUES
    ('rule-2026-0001', 'Office merchant rule',         'MERCHANT_NAME',    'office',              0.00,   TRUE),
    ('rule-2026-0002', 'Cloud tools recurring rule',   'RECURRING_CHARGE', 'cloud_tools_example', 10.00,  TRUE),
    ('rule-2026-0003', 'Fuel MCC rule',                'MCC_CODE',         'fuel',                0.00,   TRUE),
    ('rule-2026-0004', 'Amount threshold rule',        'AMOUNT_THRESHOLD', 'threshold_100',       100.00, TRUE),
    ('rule-2026-0005', 'Inactive grocery review rule', 'MERCHANT_NAME',    'grocery',             0.00,   FALSE);

-- ---------------------------------------------------------------------------
-- expense.transaction
-- 6 transactions:
--   * txn-0001..0004 are classified (matched_rule_id + classified_at set).
--   * txn-0005 and txn-0006 are unclassified: matched_rule_id IS NULL and
--     classified_at IS NULL. This exercises the nullable-FK path.
-- ---------------------------------------------------------------------------
INSERT INTO expense.transaction (
    id, account_id, merchant_id, matched_rule_id,
    amount, transaction_kind, occurred_at, classified_at
) VALUES
    ('txn-2026-0001', 'acct-2026-ops',   'merch-2026-0001', 'rule-2026-0001',
        42.75,  'DEDUCTIBLE',     '2026-05-01T09:15:00Z', '2026-05-01T09:20:00Z'),
    ('txn-2026-0002', 'acct-2026-ops',   'merch-2026-0002', 'rule-2026-0002',
        129.00, 'DEDUCTIBLE',     '2026-05-02T11:00:00Z', '2026-05-02T11:05:00Z'),
    ('txn-2026-0003', 'acct-2026-field', 'merch-2026-0004', 'rule-2026-0003',
        58.40,  'DEDUCTIBLE',     '2026-05-03T07:42:00Z', '2026-05-03T07:45:00Z'),
    ('txn-2026-0004', 'acct-2026-ops',   'merch-2026-0003', 'rule-2026-0005',
        24.18,  'NON_DEDUCTIBLE', '2026-05-04T18:30:00Z', '2026-05-04T18:35:00Z'),
    -- Unclassified: ingested but the classifier hasn't run / nothing matched.
    ('txn-2026-0005', 'acct-2026-field', 'merch-2026-0005', NULL,
        12.00,  'UNCLASSIFIED',   '2026-05-05T13:10:00Z', NULL),
    ('txn-2026-0006', 'acct-2026-ops',   'merch-2026-0001', NULL,
        7.50,   'UNCLASSIFIED',   '2026-05-06T08:55:00Z', NULL);

COMMIT;

-- ---------------------------------------------------------------------------
-- Intentional failure test (runs OUTSIDE the seed transaction above).
--
-- Purpose: prove the CHECK constraint
--   transaction_amount_non_negative  (amount >= 0)
-- actually fires. Wrapped in BEGIN/ROLLBACK so it leaves no residue even on
-- the off chance the INSERT somehow succeeds.
--
-- Expected error from PostgreSQL:
--   ERROR:  new row for relation "transaction" violates check constraint
--           "transaction_amount_non_negative"
-- ---------------------------------------------------------------------------
BEGIN;

INSERT INTO expense.transaction (
    id, account_id, merchant_id, matched_rule_id,
    amount, transaction_kind, occurred_at, classified_at
) VALUES (
    'txn-2026-BAD1', 'acct-2026-ops', 'merch-2026-0001', NULL,
    -1.00, 'UNCLASSIFIED', '2026-05-07T10:00:00Z', NULL
);

ROLLBACK;
