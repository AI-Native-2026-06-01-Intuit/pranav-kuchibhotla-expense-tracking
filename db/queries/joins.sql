SET search_path TO expense, public;

-- INNER JOIN: every transaction paired with its merchant.
SELECT
    t.id            AS transaction_id,
    t.amount        AS amount,
    t.occurred_at   AS occurred_at,
    m.display_name  AS merchant_name,
    m.merchant_kind AS merchant_kind
FROM expense.transaction AS t
INNER JOIN expense.merchant AS m
    ON m.id = t.merchant_id
ORDER BY t.occurred_at, t.id;

-- LEFT JOIN: every merchant with its transaction count, including zeros.
SELECT
    m.id            AS merchant_id,
    m.display_name  AS display_name,
    m.merchant_kind AS merchant_kind,
    COUNT(t.id)     AS transaction_count
FROM expense.merchant AS m
LEFT JOIN expense.transaction AS t
    ON t.merchant_id = m.id
GROUP BY m.id, m.display_name, m.merchant_kind
ORDER BY transaction_count DESC, m.id;
