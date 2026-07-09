-- verify.sql
-- Read-only sanity checks for the expense schema. Safe to run after
-- V1__schema.sql + V2__seed.sql. All queries use ORDER BY for stable output.

-- 1. Row counts per table, returned as a single result set.
SELECT 'expense.merchant'    AS table_name, COUNT(*) AS row_count FROM expense.merchant
UNION ALL
SELECT 'expense.rule'        AS table_name, COUNT(*) AS row_count FROM expense.rule
UNION ALL
SELECT 'expense.transaction' AS table_name, COUNT(*) AS row_count FROM expense.transaction
ORDER BY table_name;

-- 2. Transaction detail with merchant display_name and matched rule_name.
--    LEFT JOIN on expense.rule so unclassified transactions still appear
--    (matched_rule_id IS NULL -> rule_name comes back NULL).
SELECT
    t.id                AS transaction_id,
    t.account_id,
    m.display_name      AS merchant_display_name,
    r.rule_name         AS matched_rule_name,
    t.amount,
    t.transaction_kind,
    t.occurred_at
FROM expense.transaction t
INNER JOIN expense.merchant m ON m.id = t.merchant_id
LEFT  JOIN expense.rule     r ON r.id = t.matched_rule_id
ORDER BY t.occurred_at, t.id;

-- 3. Aggregate counts and totals grouped by transaction_kind.
SELECT
    transaction_kind,
    COUNT(*)            AS transaction_count,
    SUM(amount)         AS total_amount
FROM expense.transaction
GROUP BY transaction_kind
ORDER BY transaction_kind;

-- 4. Aggregate counts and totals grouped by merchant. INNER JOIN is fine
--    here because every transaction has a non-null merchant_id.
SELECT
    m.id                AS merchant_id,
    m.display_name      AS merchant_display_name,
    COUNT(t.id)         AS transaction_count,
    COALESCE(SUM(t.amount), 0) AS total_amount
FROM expense.merchant m
LEFT JOIN expense.transaction t ON t.merchant_id = m.id
GROUP BY m.id, m.display_name
ORDER BY m.id;
